"""ChatService —— 聊天链接采集编排服务（独立板块）。

职责：
- 复用 BrowserManager / SessionManager 基础设施（只调用，不改动原模块）。
- 目标搜索：好友（spotlight relation）+ 群聊（会话列表）→ 候选列表。
- 目标确认后的采集：打开会话 → 校验 → 抽链接 → 替换式持久化 → 最近目标。
- 每次操作在调用线程内自建/复用浏览器（Playwright 线程绑定，与作品采集一致）。
"""
from __future__ import annotations

from typing import Callable, List, Optional

from app.chat.collector import ChatLinkCollector
from app.chat.models import (
    CHAT_TYPE_FRIEND,
    ChatCandidate,
    ChatCollectResult,
    ChatTarget,
    merge_friend_info,
)
from app.chat.provider import ChatProvider
from app.chat.resolver import ChatTargetResolver
from app.chat.search import ChatSearch
from app.chat.store import ChatStore, target_stable_key
from app.collector.browser import BrowserManager
from app.collector.exceptions import LoginRequired
from app.collector.session import SessionManager
from app.core.models import Account

ProgressCallback = Callable[[str], None]


class ChatService:
    def __init__(self, base_dir: str, config, db, logger=None):
        self.base_dir = base_dir
        self.config = config
        self.db = db
        self.logger = logger
        self.store = ChatStore(db)
        # 由 UI 设置：True = 强制有窗口运行（用户可亲眼看到程序进入对话框的过程）
        self.show_browser = False

    def _log(self, level: str, msg: str, *args) -> None:
        """聊天模块统一日志出口（没有 logger 时静默跳过）。"""
        if self.logger is None:
            return
        try:
            getattr(self.logger, level)(msg, *args)
        except Exception:
            pass

    # ---- 基础设施（与作品采集共用配置，不改其行为） ----
    def _build_browser(self) -> BrowserManager:
        headless = bool(self.config.get("browser_headless"))
        if getattr(self, "show_browser", False):
            headless = False          # 用户要求可视化：一定开窗口
        return BrowserManager(
            headless=headless,
            proxy=self.config.proxy_config(),
        )

    def _build_session(self) -> SessionManager:
        import os
        return SessionManager(data_dir=os.path.join(self.base_dir, "data"))

    def _open_context(self, account: Account):
        browser = self._build_browser()
        session = self._build_session()
        context = browser.new_context(session.user_data_dir_for(account))
        return browser, session, context

    # ---- 目标搜索 ----
    def search_targets(self, account: Account, query: str,
                       chat_type: str = "") -> dict:
        """返回 {"friends": [...], "groups": [...], "candidates": [...], "error": ""}

        一次浏览器会话同时取好友列表与会话列表，按类型过滤出候选。
        """
        resolver = ChatTargetResolver(ChatSearch())
        provider = ChatProvider()
        browser, session, context = self._open_context(account)
        self._log("info", "搜索目标: account=%s query=%r", account.username, query)
        try:
            page, conversations, friends = provider.open_messages_snapshot(
                context, login_check=session.ensure_login)
            session.ensure_login(page)  # 登录/验证失效抛 LoginRequired（与作品采集一致）
            friends_c = [c for c in resolver.find_candidates(
                query, CHAT_TYPE_FRIEND, friends, conversations)]
            groups_c = [c for c in resolver.find_candidates(
                query, "group", friends, conversations)]
            return {
                "friends": friends_c,
                "groups": groups_c,
                "candidates": friends_c + groups_c,
                "conversation_count": len(conversations),
                "friend_count": len(friends),
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            self._log("error", "搜索目标失败: %s: %s", type(exc).__name__, exc)
            raise
        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.stop()  # 必须 stop：否则 Playwright driver 进程泄漏

    # ---- 会话列表浏览（免关键词，直接从消息列表拉取） ----
    def list_all_targets(self, account: Account,
                         on_stage: Optional[ProgressCallback] = None) -> dict:
        """拉取当前账号消息页的完整会话列表（好友单聊 + 群聊）。

        返回 {"conversations": [...], "friends": [...], "error": ""}。
        会话项已用好友 API 数据补齐 @用户名 / sec_uid（按 uid 关联）。
        on_stage: 阶段回调，用于 UI 实时反馈（整个流程约 15~40 秒）。
        """
        provider = ChatProvider()
        browser, session, context = self._open_context(account)
        self._log("info", "拉取会话列表: account=%s", account.username)
        try:
            page, conversations, friends = provider.open_messages_snapshot(
                context, on_stage=on_stage, login_check=session.ensure_login)
            session.ensure_login(page)
            merge_friend_info(conversations, friends)
            self._log("info", "会话列表完成: conversations=%d friends=%d",
                      len(conversations), len(friends))
            return {
                "conversations": conversations,
                "friends": friends,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            self._log("error", "拉取会话列表失败: %s: %s", type(exc).__name__, exc)
            raise
        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.stop()  # 必须 stop：否则 Playwright driver 进程泄漏

    # ---- 消息功能一键登录（有窗口，人工登录一次） ----
    def open_messages_login(self, account: Account, timeout_s: int = 300,
                            on_status: Optional[ProgressCallback] = None) -> bool:
        """弹出有窗口浏览器打开消息页，等用户人工登录（轮询 sessionid）。

        登录成功（拿到 sessionid cookie）后自动关闭窗口并返回 True。
        使用与采集相同的账号 session 目录，登录态落盘后永久生效。
        """
        def status(msg: str) -> None:
            if on_status:
                try:
                    on_status(msg)
                except Exception:
                    pass

        browser = BrowserManager(headless=False, proxy=self.config.proxy_config())
        session = self._build_session()
        context = browser.new_context(session.user_data_dir_for(account))
        try:
            page = context.new_page()
            page.goto("https://www.tiktok.com/messages",
                      wait_until="domcontentloaded", timeout=60000)
            import time
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                cookies = context.cookies("https://www.tiktok.com/")
                if any(c.get("name") == "sessionid" for c in cookies):
                    status("登录成功，正在保存登录态…")
                    page.wait_for_timeout(3000)  # 让会话列表 WS 建立后再关
                    return True
                status("等待登录中…（请在弹出的浏览器里登录 TikTok 账号）")
                page.wait_for_timeout(2000)
            return False
        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.stop()

    # ---- 目标确认 + 采集 ----
    def build_target(self, candidate: ChatCandidate) -> ChatTarget:
        """候选 → 最终目标（好友需补 conversation_id 时由 UI 传入会话列表，
        简化：好友候选在 search_targets 阶段已尽力从会话列表关联）。"""
        return ChatTarget(
            chat_type=candidate.chat_type, name=candidate.name,
            conversation_id=candidate.conversation_id, handle=candidate.handle,
            uid=candidate.uid, sec_uid=candidate.sec_uid)

    def collect(self, account: Account, target: ChatTarget, count: int,
                on_progress: Optional[ProgressCallback] = None,
                stop_event=None,
                on_ratio: Optional[ProgressCallback] = None) -> ChatCollectResult:
        collector = ChatLinkCollector(ChatProvider())
        browser, session, context = self._open_context(account)
        self._log("info", "开始采集: account=%s target=%s(%s) cid=%s count=%d",
                  account.username, target.name, target.chat_type,
                  target.conversation_id, count)
        try:
            # 登录态检查合并进采集流程（进页后立刻校验），
            # 不再单独开探测页 —— 省掉一次完整页面加载（约 5~8 秒）。
            result = collector.collect(context, target, count, on_progress=on_progress,
                                       stop_event=stop_event,
                                       login_check=session.ensure_login,
                                       on_ratio=on_ratio)
        except Exception as exc:  # noqa: BLE001
            self._log("error", "采集异常: target=%s %s: %s",
                      target.name, type(exc).__name__, exc)
            raise
        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.stop()  # 必须 stop：否则 Playwright driver 进程泄漏

        self._log("info", "采集结束: target=%s status=%s links=%d error=%s",
                  target.name, result.status, len(result.links), result.error or "-")
        for it in result.links:
            self._log("info", "  链接: %s", it.video_url)

        if result.status in ("completed", "partial", "empty", "stopped"):
            stable = target_stable_key(target)
            urls = [it.video_url for it in result.links]
            self.store.replace_links(stable, urls)
            self.store.upsert_target(target)
        return result

    # ---- 最近目标 / 历史链接 ----
    def recent_targets(self, limit: int = 5) -> List[ChatTarget]:
        return self.store.recent_targets(limit)

    def links_for(self, target: ChatTarget) -> List[str]:
        return self.store.links_for(target_stable_key(target))
