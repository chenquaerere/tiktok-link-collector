"""ChatSearch —— 聊天目标搜索（好友 / 群聊）。

匹配规则（对齐需求 §四/§五）：
- 好友：输入 @handle / 用户号 → 精确优先；输入名称 → 模糊匹配，全部结果返回由用户选择。
- 群聊：按群名称匹配会话列表；**不支持群号搜索**（探针结论，不伪造），
  群号仅作为命中后的展示字段。

数据源：
- 好友：ChatProvider.list_friends（/api/im/spotlight/relation，含 uid/sec_uid）
- 群聊：ChatProvider.list_conversations（DOM 会话列表，纯数字 conversation_id）
"""
from __future__ import annotations

from typing import List

from app.chat.models import CHAT_TYPE_FRIEND, CHAT_TYPE_GROUP, ChatCandidate


def _norm(s: str) -> str:
    return (s or "").strip().lower().lstrip("@")


class ChatSearch:
    def search_friends(self, query: str, friends: List[ChatCandidate]) -> List[ChatCandidate]:
        """好友搜索：@handle/uid 精确优先，名称模糊其次。"""
        q = _norm(query)
        if not q:
            return []
        exact: List[ChatCandidate] = []
        fuzzy: List[ChatCandidate] = []
        for f in friends:
            handle = _norm(f.handle)
            uid = (f.uid or "").strip()
            name = _norm(f.name)
            if q == handle or (q.isdigit() and q == uid):
                exact.append(f)
            elif q in handle or q in name:
                fuzzy.append(f)
        return exact + fuzzy

    def search_groups(self, query: str, conversations: List[ChatCandidate]) -> List[ChatCandidate]:
        """群聊搜索：仅按群名称匹配（会话列表里的群项）。"""
        q = _norm(query)
        if not q:
            return []
        exact: List[ChatCandidate] = []
        fuzzy: List[ChatCandidate] = []
        for c in conversations:
            if c.chat_type != CHAT_TYPE_GROUP:
                continue
            name = _norm(c.name)
            if q == name:
                exact.append(c)
            elif q in name:
                fuzzy.append(c)
        return exact + fuzzy

    def search_any(self, query: str, friends: List[ChatCandidate],
                   conversations: List[ChatCandidate]) -> List[ChatCandidate]:
        """不区分类型搜索：好友在前，群聊在后（供「全部」视图）。"""
        return self.search_friends(query, friends) + self.search_groups(query, conversations)
