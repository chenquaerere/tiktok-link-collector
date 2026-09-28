"""ProfileCollector —— 账号主页作品采集（P10）。

组合 BrowserManager / SessionManager / TikTokProvider / VideoParser，
完成单账号主页作品的流式采集。

关键设计：
- 单账号串行：一次只处理一个账号，采集完（或失败）才进入下一个。
- 数据来源优先网络响应（/api/post/item_list/），不依赖 DOM 相对时间。
- 通过 on_item(item) -> bool 回调把每条作品交给上层（引擎）做日期判定/去重/入库；
  回调返回 False 表示「达到数量或确认无更多目标日期作品」，立即停止本账号。
- 滚动触发 item_list 分页；连续多次滚动无新作品视为「没有更多作品」。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from app.core.models import Account, ParsedVideoItem

from .exceptions import RateLimited

# on_item 回调：返回 True 继续采集，False 停止本账号
ItemCallback = Callable[[ParsedVideoItem], bool]


class ProfileCollector:
    def __init__(
        self,
        browser,
        session,
        provider,
        parser,
        initial_wait_ms: int = 4000,
        scroll_wait_ms: int = 1200,
        max_scrolls: int = 30,
        idle_scrolls_before_stop: int = 4,
    ):
        self.browser = browser
        self.session = session
        self.provider = provider
        self.parser = parser
        self.initial_wait_ms = initial_wait_ms
        self.scroll_wait_ms = scroll_wait_ms
        self.max_scrolls = max_scrolls
        self.idle_scrolls_before_stop = idle_scrolls_before_stop

    def fetch_nickname(self, account: Account) -> str:
        """只取账号昵称（TikTok 显示名），不采集作品。

        数据来源与采集完全一致：首屏 `/api/post/item_list/` 响应里的
        `author.nickname` —— **无需额外接口请求**，代价就是打开一次主页。
        供「刷新昵称」功能给已有账号补昵称使用。

        返回昵称；取不到（未登录/无作品/被风控）时返回空串。
        """
        context = self.browser.new_context(self.session.user_data_dir_for(account))
        bodies: List[str] = []
        page = None
        try:
            def on_response(resp):
                try:
                    if ("/api/post/item_list/" in resp.url
                            and "json" in resp.headers.get("content-type", "")):
                        body = resp.text()
                        if body:
                            bodies.append(body)
                except Exception:  # noqa: BLE001
                    pass

            # ⚠️ 监听必须在导航之前注册（首屏响应可能在 <1s 内返回）
            page = self.provider.load_profile(context, account.username,
                                              on_response=on_response)
            self.session.ensure_login(page)
            page.wait_for_timeout(self.initial_wait_ms)

            for body in bodies:
                for item in self.parser.parse_item_list(body):
                    if item.nickname:
                        return item.nickname.strip()
            return ""
        finally:
            try:
                if page is not None:
                    page.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass

    def fetch(self, account: Account) -> List[ParsedVideoItem]:
        """满足旧 Fetcher 协议：一次性返回全部解析结果（测试/简单场景用）。"""
        out: List[ParsedVideoItem] = []
        self.collect(account, lambda it: (out.append(it), True)[1])
        return out

    def collect(self, account: Account, on_item: ItemCallback) -> Dict:
        """单账号流式采集。返回诊断 dict。"""
        diag = {
            "found": 0,
            "item_list_requests": 0,
            "scrolls": 0,
            "stopped_by_callback": False,
            "rate_limited": False,
            "author_nickname": "",   # 账号昵称：从 item_list 的 author.nickname 顺手取回
            "pinned_skipped": 0,     # 置顶作品条数（供诊断：置顶不占「最新 N 条」名额）
            "create_times": [],  # 记录 createTime 顺序，供排序可靠性诊断（已排除置顶）
        }

        context = self.browser.new_context(self.session.user_data_dir_for(account))
        try:
            # 监听 item_list 网络响应。
            # ⚠️ 必须在导航**之前**注册（通过 load_profile 的 on_response 参数）：
            #    首屏那次响应 = 最新一批作品，晚注册会漏掉它 → 只能拿到更旧的作品。
            queue: List[str] = []

            def on_response(resp):
                try:
                    url = resp.url
                    if "/api/post/item_list/" in url and "json" in resp.headers.get("content-type", ""):
                        if resp.status == 429:
                            diag["rate_limited"] = True
                            return
                        body = resp.text()
                        if body:
                            queue.append(body)
                            diag["item_list_requests"] += 1
                except Exception:
                    pass

            page = self.provider.load_profile(context, account.username,
                                              on_response=on_response)
            self.session.ensure_login(page)  # 登录/验证失效抛 LoginRequired

            # 等待首批响应落地
            page.wait_for_timeout(self.initial_wait_ms)

            emitted_ids = set()
            idle = 0
            for _ in range(self.max_scrolls):
                new_items = 0
                while queue:
                    body = queue.pop(0)
                    for item in self.parser.parse_item_list(body):
                        if not item.video_id or item.video_id in emitted_ids:
                            continue
                        emitted_ids.add(item.video_id)
                        diag["found"] += 1
                        new_items += 1
                        # 昵称：零额外请求，从首个带昵称的作品上取
                        if not diag["author_nickname"] and item.nickname:
                            diag["author_nickname"] = item.nickname.strip()
                        # 排序诊断：**排除置顶作品**再记录 createTime ——
                        # 置顶作品被排在列表最前、时间却是旧的，会把「顺序是否
                        # 时间倒序」的判定拉成异常，造成误告警。
                        if item.raw_publish_time is not None and not item.is_pinned:
                            diag["create_times"].append(item.raw_publish_time)
                        # 交给上层；False → 停止本账号
                        if not on_item(item):
                            diag["stopped_by_callback"] = True
                            return diag

                # 滚动触发更多 item_list
                try:
                    page.mouse.wheel(0, 2500)
                except Exception:
                    pass
                page.wait_for_timeout(self.scroll_wait_ms)
                diag["scrolls"] += 1

                if new_items == 0:
                    idle += 1
                    if idle >= self.idle_scrolls_before_stop:
                        break  # 连续多次无新作品 → 没有更多
                else:
                    idle = 0

            # 限流检测：一个作品都没采到且命中 429 → 抛退避异常，交由引擎指数退避
            if diag.get("rate_limited") and diag["found"] == 0:
                raise RateLimited("触发 TikTok 限流(HTTP 429)，需退避等待后重试")

            return diag
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
