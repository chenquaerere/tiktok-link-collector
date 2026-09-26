"""ChatLinkCollector —— 聊天分享链接采集。

真实链路（2026-09-26 探针实测，见 diagnostics/chat_*_probe.py）：
    在消息页点开目标会话（必须真的进入对话框）
    → 聊天面板 DivChatBox 内每张「分享卡片」的 React props 里带 itemId（= 作品 ID）
    → 用 itemId 调 /api/im/item_detail/ 拿作者 / 类型（视频 or 图文）
    → 拼出真实链接 https://www.tiktok.com/@作者/video|photo/ID

关键约束：
1. **作用域必须限定在聊天面板内**：整页扫描会抓到左侧会话列表预览、
   页头等位置的隐藏链接（实测这些隐藏链接恒为同一账号的作品），
   导致「不管选哪个会话都拿到同一批错误链接」（用户实测反馈的 bug）。
2. **顺序按垂直位置 下→上**：聊天记录自上而下按时间排列，最下面那条最新。
3. 进入会话后必须二次校验聊天头部 = 目标（需求 §八），不一致立即停止。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.chat.models import (
    ChatCollectResult,
    ChatLinkItem,
    ChatTarget,
    extract_video_id,
)
from app.chat.resolver import ChatTargetResolver
from app.collector.exceptions import LoginRequired

ProgressCallback = Callable[[str], None]   # on_progress(stage_text)


class ChatLinkCollector:
    def __init__(self, provider, resolver: Optional[ChatTargetResolver] = None,
                 scroll_rounds: int = 15, scroll_wait_ms: int = 1500,
                 idle_rounds_before_stop: int = 3, resolve_chunk: int = 6):
        self.provider = provider
        self.resolver = resolver or ChatTargetResolver()
        self.scroll_rounds = scroll_rounds
        self.scroll_wait_ms = scroll_wait_ms
        self.idle_rounds_before_stop = idle_rounds_before_stop
        self.resolve_chunk = resolve_chunk

    def collect(self, context, target: ChatTarget, count: int,
                on_progress: Optional[ProgressCallback] = None,
                stop_event=None, login_check=None,
                on_ratio: Optional[Callable[[float], None]] = None) -> ChatCollectResult:
        """采集一个会话的最新 N 条分享链接。

        stop_event: threading.Event，置位后尽快停止并返回 status="stopped"。
        login_check: 进页后立即调用的登录态检查（避免另开一个探测页，省一次页面加载）。
        on_ratio: 进度回调（0.0~1.0），用于驱动界面进度条。
        """
        diag: Dict[str, Any] = {"opened": False, "verified": False, "scrolls": 0,
                                "cards": 0, "resolved": 0, "skipped": 0}
        result = ChatCollectResult(target=target, requested_count=count,
                                   diagnostics=diag)

        def emit(stage: str) -> None:
            if on_progress:
                try:
                    on_progress(stage)
                except Exception:
                    pass

        def ratio(v: float) -> None:
            if on_ratio:
                try:
                    on_ratio(max(0.0, min(1.0, float(v))))
                except Exception:
                    pass

        def stopped() -> bool:
            try:
                return bool(stop_event is not None and stop_event.is_set())
            except Exception:  # noqa: BLE001
                return False

        page = self.provider.load_messages(context)
        try:
            if login_check is not None:
                login_check(page)       # 未登录立刻抛 LoginRequired（快速失败）

            # 1) 真的进入目标对话框
            emit("打开目标聊天…")
            if not target.conversation_id:
                result.status = "failed"
                result.error = "目标缺少会话唯一标识（conversation_id），无法定位聊天"
                return result
            if not self.provider.open_conversation(page, target.conversation_id):
                result.status = "failed"
                result.error = "会话列表中找不到目标聊天（可能已被删除或未开过对话）"
                return result
            diag["opened"] = True

            # 2) 目标校验（不一致立即停止，绝不采错误聊天的内容）
            header = self.provider.chat_header_text(page)
            if not self.resolver.verify_target(target, header):
                result.status = "failed"
                result.error = (f"目标校验失败：当前聊天头部为「{header[:60]}」，"
                                f"与所选目标「{target.name}」不一致，已停止采集")
                return result
            diag["verified"] = True
            emit("已进入目标对话框，开始读取分享记录…")

            # 3) 滚动加载历史 + 逐张卡片解析（下→上 = 最新→最旧）
            found: List[ChatLinkItem] = []
            seen_ids: set = set()
            idle = 0
            for round_no in range(self.scroll_rounds):
                if stopped():
                    result.status = "stopped"
                    result.error = "已手动停止"
                    break
                cards = self.provider.extract_chat_items(page)
                diag["cards"] = max(diag["cards"], len(cards))

                # 本轮新出现的卡片（已按 下→上 排序）：取够数量就不再解析更旧的
                fresh = [c["item_id"] for c in cards if c["item_id"] not in seen_ids]
                seen_ids.update(fresh)
                need = fresh[:max(0, count - len(found))]
                if need:
                    details = self.provider.resolve_items(page, need,
                                                          chunk=self.resolve_chunk)
                    for iid in need:
                        info = details.get(iid) or {}
                        if not info.get("ok") or not info.get("id"):
                            diag["skipped"] += 1
                            continue
                        url = self.provider.build_item_url(
                            info["id"], info.get("unique_id", ""),
                            bool(info.get("is_photo")))
                        found.append(ChatLinkItem(
                            video_url=url, video_id=extract_video_id(url),
                            order=len(found)))
                    diag["resolved"] = len(found)

                emit(f"已读取分享记录 {len(found)}/{count} 条"
                     f"（第 {round_no + 1}/{self.scroll_rounds} 轮加载中）")
                ratio(len(found) / count if count else 0.0)
                if len(found) >= count:
                    break

                before = len(seen_ids)
                self.provider.scroll_history(page, rounds=1, wait_ms=self.scroll_wait_ms)
                diag["scrolls"] += 1
                after_cards = self.provider.extract_chat_items(page)
                diag["cards"] = max(diag["cards"], len(after_cards))
                if len(seen_ids) == before:
                    idle += 1
                    if idle >= self.idle_rounds_before_stop:
                        break          # 没有更多历史了
                else:
                    idle = 0

            result.links = found[:count]
            actual = len(result.links)
            if result.status == "stopped":
                pass
            elif actual >= count:
                result.status = "completed"
            elif actual > 0:
                result.status = "partial"
            else:
                result.status = "empty"
                if not diag["cards"]:
                    result.error = ("该聊天窗口内没有发现分享卡片"
                                    "（可能对方没有分享过作品，或消息尚未加载出来）")
                elif diag["skipped"]:
                    result.error = (f"发现 {diag['cards']} 张卡片，"
                                    f"但 {diag['skipped']} 条详情解析失败")
            return result
        except LoginRequired:
            raise
        except Exception as exc:  # noqa: BLE001 —— 单目标失败不向上抛裸异常
            result.status = "failed"
            result.error = str(exc) or type(exc).__name__
            return result
        finally:
            try:
                page.close()
            except Exception:
                pass
