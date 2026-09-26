"""ChatTargetResolver —— 把用户输入解析为「带稳定唯一标识的采集目标」。

流程（对齐需求 §三目标选择流程）：
    输入(名称/好友号/群号) → 搜索候选 → 用户选择 → 确认目标(ChatTarget)

核心职责：
- 好友：候选来自好友列表（sec_uid 稳定），并从会话列表补齐 conversation_id
  （采集打开会话必须用 conversation_id）。
- 群聊：候选来自会话列表（conversation_id 即群 ID）。
- 不做随机选择：多候选一律交上层（UI）让用户确认。
"""
from __future__ import annotations

from typing import List, Optional

from app.chat.models import (
    CHAT_TYPE_FRIEND,
    CHAT_TYPE_GROUP,
    ChatCandidate,
    ChatTarget,
    is_dm_conversation_id,
)
from app.chat.search import ChatSearch


class ChatTargetResolver:
    def __init__(self, search: Optional[ChatSearch] = None):
        self.search = search or ChatSearch()

    # ---- 搜索候选 ----
    def find_candidates(self, query: str, chat_type: str,
                        friends: List[ChatCandidate],
                        conversations: List[ChatCandidate]) -> List[ChatCandidate]:
        if chat_type == CHAT_TYPE_FRIEND:
            return self.search.search_friends(query, friends)
        if chat_type == CHAT_TYPE_GROUP:
            return self.search.search_groups(query, conversations)
        return self.search.search_any(query, friends, conversations)

    # ---- 候选 → 最终目标 ----
    def build_target(self, candidate: ChatCandidate,
                     conversations: List[ChatCandidate],
                     self_uid: str = "") -> ChatTarget:
        """把用户选中的候选固化为 ChatTarget。

        好友候选若缺 conversation_id，则从会话列表里按对端 uid 反查补齐；
        找不到（尚未开过聊天）时 conversation_id 留空，由上层提示。
        """
        conv_id = candidate.conversation_id
        if candidate.chat_type == CHAT_TYPE_FRIEND and not conv_id and candidate.uid:
            conv_id = self._find_dm_conversation_id(candidate.uid, conversations, self_uid)
        return ChatTarget(
            chat_type=candidate.chat_type,
            name=candidate.name,
            conversation_id=conv_id,
            handle=candidate.handle,
            uid=candidate.uid,
            sec_uid=candidate.sec_uid,
        )

    @staticmethod
    def _find_dm_conversation_id(peer_uid: str,
                                 conversations: List[ChatCandidate],
                                 self_uid: str = "") -> str:
        for c in conversations:
            if c.chat_type == CHAT_TYPE_FRIEND and is_dm_conversation_id(c.conversation_id):
                parts = [p for p in c.conversation_id.split(":") if p.isdigit()]
                if peer_uid in parts:
                    return c.conversation_id
        return ""

    # ---- 采集时目标校验（需求 §八） ----
    @staticmethod
    def verify_target(target: ChatTarget, header_text: str) -> bool:
        """用聊天头部文本验证当前打开的会话确实是目标。

        匹配任一 token（名称 / @用户名）即视为一致；
        群聊额外要求头部含 members 字样或不含 @（避免误入同名好友）。
        """
        header = (header_text or "").strip()
        if not header:
            return False
        tokens = [t for t in target.verify_text_tokens() if t]
        hit = any(t.lower() in header.lower() for t in tokens)
        if not hit:
            return False
        if target.chat_type == CHAT_TYPE_GROUP:
            # 群聊头部形如 "群名 ... N members"；若出现 @handle 则可能是好友同名
            if target.handle and f"@{target.handle}".lower() in header.lower():
                return False
        return True
