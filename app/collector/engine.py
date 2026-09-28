"""CollectEngine —— 正式采集编排层。

职责：
- 严格单账号串行：一个账号完整采集并保存后才进入下一个。
- 每确认一个作品立即写库（insert_video + collect_logs），程序崩溃/停止不丢已采数据。
- 账号间可配置等待间隔（account_interval_seconds）。
- 进度回调 on_progress。
- 停止/恢复：已采数据持久化，未开始账号 PENDING，当前账号 PARTIAL/FAILED。
- 异常隔离：单账号失败（含 LoginRequired）不阻断整体任务。

采集规则（2026-09-25 起，用户规定）：
- **不过滤日期**：直接抓取账号当前最新的 N 条作品（N = 每账号数量）。
  不管是今天、昨天还是更早，按主页时间倒序取前 N 条。
- 发布时间尽力解析并记录（createTime），无法确认的照常采集，publish_date 记空。
- **替换式记录**：新任务开始时删除本次所有账号的历史作品记录，
  多次采集（含同日多次测试）一律按最后一次的结果替换。
- 每日链接日志同日文件同样按最后一次运行整体替换。
"""
from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from app.core.collect_logic import recent_dates, resolve_item
from app.core.date_resolver import DateResolver
from app.core.dedup import VideoDedup
from app.core.models import (
    Account,
    AccountCollectResult,
    DateConfidence,
    Video,
)
from app.core.url_normalizer import normalize_url
from app.collector.exceptions import LoginRequired, RateLimited
from app.log.logger import get_logger

# on_progress(current_index, total, account_username, status, detail)
ProgressCallback = Callable[[int, int, str, str, dict], None]


class CollectEngine:
    def __init__(
        self,
        db,
        collector,
        resolver: DateResolver,
        max_retry: int = 1,
        account_interval_seconds: float = 4.0,
        consecutive_older_stop: int = 3,
        daily_links=None,
        logger=None,
    ):
        self.db = db
        self.collector = collector          # ProfileCollector
        self.resolver = resolver
        self.max_retry = max(0, max_retry)
        self.account_interval_seconds = max(0.0, account_interval_seconds)
        self.consecutive_older_stop = max(1, consecutive_older_stop)
        self.daily_links = daily_links      # 可选 DailyLinksLog，作品入库后追加链接
        self.logger = logger or get_logger("collector.engine")
        self._stop = threading.Event()
        self._run_urls: List[str] = []  # 本次运行采集的链接（链接日志替换用）
        self._rate_backoff = 0          # 限流退避等级（0 无退避，随 429 递增）

    # ---- 停止控制 ----
    def request_stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        self._stop.clear()

    def _stopped(self) -> bool:
        return self._stop.is_set()

    # ---- 主入口 ----
    def run(
        self,
        accounts: List[Account],
        target_date: str,
        task_id: Optional[str] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> dict:
        task_id = task_id or self.db.next_task_id(target_date)
        self.db.insert_task(task_id, target_date=target_date, status="running")

        # 确保账号已入库（幂等），保证 task_accounts / videos 外键有效
        for acc in accounts:
            self.db.insert_account(acc)

        # 替换式记录：删除本次所有账号的历史作品（多次采集按最后一次替换）
        for acc in accounts:
            try:
                removed = self.db.delete_videos_for_account(acc.account_id)
                if removed:
                    self.logger.info("账号 @%s 旧记录已清除：%d 条（替换式记录）",
                                     acc.username, removed)
            except Exception as exc:  # noqa: BLE001 —— 清理失败不阻断采集
                self.logger.warning("账号 @%s 旧记录清除失败: %s", acc.username, exc)

        # ⚠️ 绝不做「跨运行去重」（历史 bug，2026-09-27 修复）
        #   旧实现：dedup = VideoDedup(initial=self.db.load_all_video_ids())
        #   把**全库已有 video_id** 装进去重器 → 重新抓取时，最新作品被当成「重复」
        #   跳过，然后继续往后捞更旧的：
        #     · 拿到的不是最新的（与「从最新开始拿」的要求相反）
        #     · 或凑不够数量 → 用户回填时发现「少了两条链接」
        #   实测后果：2026-09-24 有 40 条作品被标记「重复跳过」且**从未入库**。
        #   用户明确要求：不管之前采过没有，每次抓取都要从最新一条开始、依次取够数量。
        #   → 去重范围收窄为「单账号 + 单次采集内」（仅用于处理置顶作品在列表里
        #     重复渲染），在 _collect_once 内部新建，重试时也会重置。

        summary = {
            "task_id": task_id,
            "target_date": target_date,
            "account_count": len(accounts),
            "completed": 0, "partial": 0, "empty": 0,
            "failed": 0, "login_required": 0, "skipped": 0,
            "target_total": 0, "actual_total": 0,
            "new_videos": 0, "duplicates": 0, "unconfirmed": 0,
            "pinned_skipped": 0,     # 本次跳过的置顶作品总数（非近期，不占名额）
            "pinned_collected": 0,   # 本次额外采集的近期置顶总数（今天/昨天发布）
            "accounts": [],
        }

        total = len(accounts)
        self.logger.info("任务 %s 开始：%d 个账号，最新N条模式（记录日期 %s）",
                         task_id, total, target_date)
        self._run_urls = []  # 本次运行采到的全部链接（供链接日志整体替换）
        try:
            for idx, acc in enumerate(accounts):
                if self._stopped():
                    self.db.upsert_task_account(task_id, acc.account_id, acc.username,
                                                acc.collect_count, 0, "skipped", "任务已停止")
                    summary["skipped"] += 1
                    self._emit(on_progress, idx, total, acc.username, "skipped", {})
                    continue

                # 账号间等待（首个账号前不等）
                if idx > 0 and self.account_interval_seconds > 0:
                    self._interruptible_sleep(self.account_interval_seconds)
                    if self._stopped():
                        self.db.upsert_task_account(task_id, acc.account_id, acc.username,
                                                    acc.collect_count, 0, "skipped", "任务已停止")
                        summary["skipped"] += 1
                        continue

                result = self._collect_account(acc, task_id, target_date, on_progress, idx, total)
                self.logger.info("账号 @%s 完成：status=%s target=%d actual=%d err=%r",
                                 acc.username, result.status, result.target_count,
                                 result.actual_count, result.error_reason)
                summary["accounts"].append(result)
                summary["target_total"] += result.target_count
                summary["actual_total"] += result.actual_count
                summary["new_videos"] += result.diagnostics.get("collected", 0)
                summary["duplicates"] += result.diagnostics.get("duplicates", 0)
                summary["unconfirmed"] += result.diagnostics.get("date_unconfirmed", 0)
                summary["pinned_skipped"] += result.diagnostics.get("pinned_skipped", 0)
                summary["pinned_collected"] += result.diagnostics.get("pinned_collected", 0)

                if result.status == "completed":
                    summary["completed"] += 1
                elif result.status == "partial":
                    summary["partial"] += 1
                elif result.status == "empty":
                    summary["empty"] += 1
                elif result.status == "failed":
                    summary["failed"] += 1
                    if result.diagnostics.get("login_required"):
                        summary["login_required"] += 1

                self.db.upsert_task_account(
                    task_id, acc.account_id, acc.username,
                    result.target_count, result.actual_count,
                    result.status, result.error_reason,
                )
        finally:
            # 链接日志：按「最后一次运行」整体替换当日文件（含停止/异常场景）
            if self.daily_links is not None:
                try:
                    self.daily_links.replace(self._run_urls, day=target_date)
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("每日链接日志替换失败: %s", exc)

        # 更新任务汇总
        status = "stopped" if self._stopped() else "completed"
        self.db.update_task(
            task_id, status=status, account_count=total,
            target_total=summary["target_total"], actual_total=summary["actual_total"],
            success_count=summary["completed"] + summary["partial"],
            fail_count=summary["failed"], completed_at=_now(),
        )
        summary["status"] = status
        return summary

    # ---- 单账号采集 ----
    def _collect_account(self, acc, task_id, target_date, on_progress, idx, total):
        """采集单个账号（含重试）。

        ⚠️ 每次尝试都在 _collect_once 内新建去重集合 —— 重试时不复用，
        否则「第 1 次尝试已采到的作品」会在第 2 次尝试里被当成重复而全部跳过。
        """
        last_error = ""
        login_required = False
        attempts = 0
        for attempt in range(1, self.max_retry + 1):
            if self._stopped():
                return self._result(acc, target_date, 0, "skipped", "任务已停止", {}, [])
            try:
                result = self._collect_once(acc, task_id, target_date,
                                            on_progress, idx, total, attempt)
                self._rate_backoff = 0  # 采集成功，退避等级清零
                return result
            except LoginRequired as exc:
                login_required = True
                last_error = str(exc) or "登录态失效"
                self.logger.warning("账号 @%s 登录态失效: %s", acc.username, last_error)
                break  # 登录/验证问题重试无意义，直接判失败
            except RateLimited as exc:
                last_error = str(exc) or "触发限流"
                attempts = attempt
                self.logger.warning("账号 @%s 第 %d/%d 次触发限流: %s",
                                    acc.username, attempt, self.max_retry, last_error)
                if attempt < self.max_retry:
                    self._backoff_sleep()
            except Exception as exc:  # noqa: BLE001 —— 单账号失败不得阻断整体
                last_error = str(exc) or type(exc).__name__
                attempts = attempt
                self.logger.warning("账号 @%s 第 %d/%d 次尝试失败: %s",
                                    acc.username, attempt, self.max_retry, last_error)
                if attempt < self.max_retry:
                    time.sleep(1.0)
        diag = {"login_required": login_required, "attempts": attempts or self.max_retry}
        return self._result(acc, target_date, 0, "failed", last_error, diag, [])

    def _collect_once(self, acc, task_id, target_date, on_progress, idx, total, attempt):
        diag = {
            "found": 0, "date_resolved": 0, "date_unconfirmed": 0,
            "duplicates": 0, "collected": 0,
            "pinned_skipped": 0,     # 置顶但非近期 → 跳过条数
            "pinned_collected": 0,   # 置顶且为「今天/昨天」→ 额外采集条数（不占名额）
            "attempts": attempt,
            "author_nickname": "",   # 账号昵称：从首个带昵称的作品上取（零额外请求）
        }
        # 「最新 N 条」的名额**只由非置顶作品占用**；近期置顶属于额外采集。
        non_pinned_count = 0
        # 近期日期集合（今天 / 昨天，按配置时区）—— 用于判断置顶是否值得额外采集
        recent = recent_dates(self.resolver, 2)
        collected: List[Video] = []
        # 去重范围 = **本账号 + 本次采集**。
        # 每次调用都新建集合：
        #   · 不加载库中已有 ID（否则重新抓取时最新作品会被跳过 —— 见 run() 说明）
        #   · 不跨重试复用（否则第 2 次尝试会把第 1 次采到的作品全部跳过）
        # 唯一作用是处理「同一作品在主页列表里出现两次」（如置顶作品），
        # 避免同一个视频占用两个名额、导致最终拿到的不同作品数不足。
        dedup = VideoDedup()

        def on_item(item):
            nonlocal non_pinned_count
            diag["found"] += 1

            # 0) 账号昵称：从首个带昵称的作品上取（放在最前，即使该作品随后被
            #    去重跳过/已达数量而停止，也仍能拿到昵称用于账号页辨识）。
            if not diag["author_nickname"]:
                nick = (getattr(item, "nickname", "") or "").strip()
                if nick:
                    diag["author_nickname"] = nick

            # 1) 置顶作品：**不占「最新 N 条」名额**（2026-09-28 用户实测修复）。
            #    置顶被排在列表最前（不按发布时间），若照单计入会挤掉真正新发布的作品：
            #    用户有 2 个账号各置顶 1 条，结果各少拿 1 条新作品。
            #    依据 item_list 的 `isPinnedItem=true`（探针实测：置顶 true、普通 null）。
            #    · 置顶发布于**今天 / 昨天** → 它本身就是新作品 → **额外采集**（结果多于 N 条）
            #    · 其它（较旧的置顶）→ 跳过、不采集
            extra_pinned = False
            if getattr(item, "is_pinned", False):
                resolve_item(item, self.resolver)   # 先解析时间才能判断日期
                if (item.publish_date or "") not in recent:
                    diag["pinned_skipped"] += 1
                    self.db.insert_collect_log(
                        task_id, acc.account_id,
                        f"置顶作品跳过（非近期，不占名额） video_id={item.video_id}",
                        level="info", video_id=item.video_id,
                    )
                    return True
                extra_pinned = True
                diag["pinned_collected"] += 1
                self.db.insert_collect_log(
                    task_id, acc.account_id,
                    f"置顶作品额外采集（{item.publish_date}） video_id={item.video_id}",
                    level="info", video_id=item.video_id,
                )

            # 2) 同一账号内同一作品重复出现 → 跳过且不计数，
            #    保证最终拿到的是 N 条**不同**的作品。
            #    注意顺序：放在数量检查之前，这样重复条目能被准确统计（diagnostics）。
            if dedup.is_duplicate(item.video_id):
                diag["duplicates"] += 1
                self.db.insert_collect_log(
                    task_id, acc.account_id,
                    f"同一作品重复出现，跳过 video_id={item.video_id}",
                    level="info", video_id=item.video_id,
                )
                return True

            # 3) 非置顶作品已取满 N 条 → 停止（额外采集的近期置顶不占名额）
            if not extra_pinned and non_pinned_count >= acc.collect_count:
                return False

            # 4) 解析发布时间（尽力记录；无法确认照常采集，日期记空）
            resolve_item(item, self.resolver)
            publish_time = ""
            publish_date = ""
            if item.confidence == DateConfidence.CONFIRMED.value and item.publish_datetime:
                diag["date_resolved"] += 1
                publish_time = item.publish_datetime.strftime("%Y-%m-%d %H:%M:%S")
                publish_date = item.publish_date or ""
            else:
                diag["date_unconfirmed"] += 1

            # 5) 标准化 URL 并入库
            normalized, vid, _ = normalize_url(item.raw_url, username_hint=item.username or acc.username)
            video_id = vid or item.video_id
            video = Video(
                video_id=video_id,
                account_id=acc.account_id,
                username=item.username or acc.username,
                video_url=normalized or item.raw_url,
                publish_time=publish_time,
                publish_date=publish_date,
                first_task_id=task_id,
            )
            # 立即持久化：video 唯一插入 + 采集日志
            inserted = self.db.insert_video(video)
            self.db.insert_collect_log(
                task_id, acc.account_id,
                "采集入库" if inserted else "已存在(重复)",
                level="info", video_id=video_id,
            )
            dedup.mark(video_id)
            collected.append(video)
            diag["collected"] += 1
            if not extra_pinned:
                non_pinned_count += 1
            self._run_urls.append(video.video_url)

            self._emit(on_progress, idx, total, acc.username, "collecting",
                       {"video_id": video_id, "collected": len(collected)})
            # 非置顶已达数量 → 停止本账号（额外采集的近期置顶不影响停止条件）
            return non_pinned_count < acc.collect_count

        profile_diag = self.collector.collect(acc, on_item)
        diag.update({k: profile_diag[k] for k in ("scrolls", "item_list_requests")
                     if k in profile_diag})
        diag["create_time_order"] = "descending" if self._is_descending(
            profile_diag.get("create_times", [])) else "unknown"

        # 昵称（TikTok 显示名）：采集时顺手写回账号，零额外请求。
        # 优先用 engine 自己从作品上收集的；collector 的 diag 作为兜底。
        # 用途：账号管理页显示昵称，便于辨识账号与分类。
        nickname = ((diag.get("author_nickname") or "")
                    or (profile_diag.get("author_nickname") or "")).strip()
        if nickname:
            try:
                if self.db.set_account_display_name(acc.account_id, nickname):
                    self.logger.info("账号 @%s 昵称已更新：%s", acc.username, nickname)
            except Exception as exc:  # noqa: BLE001 —— 昵称失败不影响采集
                self.logger.warning("账号 @%s 昵称写入失败: %s", acc.username, exc)

        # 可观测性：这两个信号用来区分「账号真的没作品」与「页面/监听异常」。
        # 2026-09-27 曾因「item_list 响应监听晚于页面导航」导致首屏最新一批被静默丢弃，
        # 表面现象是「拿到更旧的作品 / 数量对不上」，但日志里毫无痕迹 —— 故补上这两条告警。
        if profile_diag.get("item_list_requests", 0) == 0:
            self.logger.warning(
                "账号 @%s 未捕获到任何 item_list 响应（页面加载异常或接口变更？）",
                acc.username)
        if len(collected) > 1 and diag["create_time_order"] != "descending":
            self.logger.warning(
                "账号 @%s 作品顺序非时间倒序（create_time_order=%s）—— "
                "可能漏掉了首屏最新的一批，请检查采集结果",
                acc.username, diag["create_time_order"])

        # 状态按「非置顶作品数」判定：额外采集的近期置顶不算入目标名额，
        # 否则「只采到置顶、非置顶没采到」会被误判成完成。
        status = self._status_for(acc.collect_count, non_pinned_count)
        return self._result(acc, target_date, len(collected), status, "", diag, collected)

    # ---- helpers ----
    def _result(self, acc, target_date, actual, status, error, diag, videos):
        return AccountCollectResult(
            account_id=acc.account_id,
            username=acc.username,
            target_date=target_date,
            target_count=acc.collect_count,
            actual_count=actual,
            status=status,
            videos=videos,
            error_reason=error,
            diagnostics=diag,
        )

    @staticmethod
    def _status_for(target_count, actual):
        if actual >= target_count:
            return "completed"
        if actual > 0:
            return "partial"
        return "empty"

    @staticmethod
    def _is_descending(times: List) -> bool:
        """判断 createTime 序列是否整体递减（最新→最旧）。"""
        nums = [float(t) for t in times if t is not None]
        if len(nums) < 3:
            return True  # 样本过少，视为未知
        inversions = sum(1 for i in range(len(nums) - 1) if nums[i] < nums[i + 1])
        return inversions <= max(1, len(nums) // 10)

    def _interruptible_sleep(self, seconds: float) -> None:
        """可被停止信号打断的等待。"""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._stopped():
                return
            time.sleep(min(0.2, seconds))

    def _backoff_sleep(self) -> None:
        """限流指数退避：10s → 20s → 40s → 60s 封顶，可被停止信号打断。"""
        delay = min(60.0, 10.0 * (2 ** self._rate_backoff))
        self._rate_backoff += 1
        self.logger.info("限流退避等待 %.0f 秒后重试", delay)
        self._interruptible_sleep(delay)

    @staticmethod
    def _emit(cb, idx, total, username, status, detail):
        if cb is not None:
            try:
                cb(idx, total, username, status, detail)
            except Exception:
                pass


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
