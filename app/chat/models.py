"""聊天链接采集模块 —— 数据模型。

与作品采集模块（app.core.models）完全独立，互不引用行为语义。
唯一标识优先级（探针报告 docs/CHAT_PROBE_REPORT.md §一）：
    conversation_id（DOM data-conversation-id，稳定唯一）
    > sec_uid（好友，来自 /api/im/spotlight/relation）
    > uid（数字用户 ID / 群 ID）
    > 名称（仅展示，不作为身份判断）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# 聊天类型
CHAT_TYPE_FRIEND = "friend"   # 好友单聊
CHAT_TYPE_GROUP = "group"     # 群聊

# conversation_id 两种格式（探针 §三）
DM_ID_SEP = ":"               # DM 格式 0:1:<peerUid>:<selfUid>


def is_dm_conversation_id(conversation_id: str) -> bool:
    """0:1:A:B 格式 → 好友单聊；纯数字 → 群聊。"""
    return DM_ID_SEP in (conversation_id or "")


def peer_uid_from_dm_id(conversation_id: str, self_uid: str = "") -> str:
    """从 DM 会话 ID（0:1:<peerUid>:<selfUid>）中取出对端 uid。

    前两段（0/1）是类型标记；uid 段为 10 位以上数字，
    取两段 uid 中不等于 self_uid 的那一段。
    """
    nums = [p for p in (conversation_id or "").split(":")
            if p.isdigit() and len(p) >= 10]
    if len(nums) >= 2:
        for p in nums:
            if p != self_uid:
                return p
        return nums[0]
    return nums[0] if nums else ""


@dataclass
class ChatCandidate:
    """搜索结果里的一个可选项（好友或群聊）。"""
    chat_type: str                     # friend / group
    name: str                          # 昵称 / 群名（仅展示）
    handle: str = ""                   # 好友 @用户名（群聊为空）
    uid: str = ""                      # 数字用户 ID（好友）/ 群 ID（群聊）
    sec_uid: str = ""                  # 好友稳定 ID（群聊为空）
    conversation_id: str = ""          # DOM 会话唯一标识（最终采集依据）
    subtitle: str = ""                 # 摘要（最后消息 / 成员数）

    @property
    def display(self) -> str:
        if self.chat_type == CHAT_TYPE_GROUP:
            extra = f"  群ID：{self.uid}" if self.uid else ""
            return f"{self.name}{extra}"
        extra = f"  @{self.handle}" if self.handle else ""
        return f"{self.name}{extra}"

    @property
    def stable_key(self) -> str:
        """稳定唯一键：conversation_id 优先，其次 sec_uid，再 uid。"""
        if self.conversation_id:
            return f"conv:{self.conversation_id}"
        if self.sec_uid:
            return f"secuid:{self.sec_uid}"
        return f"uid:{self.chat_type}:{self.uid}"


@dataclass
class ChatTarget:
    """用户确认后的最终采集目标（必须带稳定唯一标识）。"""
    chat_type: str
    name: str                          # 展示名
    conversation_id: str = ""          # 会话唯一标识（核心）
    handle: str = ""                   # 好友 @用户名
    uid: str = ""
    sec_uid: str = ""

    @property
    def type_label(self) -> str:
        return "好友" if self.chat_type == CHAT_TYPE_FRIEND else "群聊"

    @property
    def detail_label(self) -> str:
        if self.chat_type == CHAT_TYPE_GROUP:
            return f"群ID：{self.uid}" if self.uid else ""
        return f"账号：@{self.handle}" if self.handle else ""

    def verify_text_tokens(self) -> List[str]:
        """采集时与聊天头部文本比对的判定 token（探针 §五）。"""
        tokens = []
        if self.name:
            tokens.append(self.name)
        if self.chat_type == CHAT_TYPE_FRIEND and self.handle:
            tokens.append(f"@{self.handle}")
        return tokens


@dataclass
class ChatLinkItem:
    """聊天里抽取到的一条视频链接。"""
    video_url: str
    video_id: str = ""                 # 从 URL 提取
    order: int = 0                     # 顺序（0 = 最新）


@dataclass
class ChatCollectResult:
    """一次聊天采集的结果。"""
    target: ChatTarget
    requested_count: int = 0
    links: List[ChatLinkItem] = field(default_factory=list)
    status: str = "completed"          # completed / partial / empty / failed / stopped
    error: str = ""
    diagnostics: dict = field(default_factory=dict)


def extract_video_id(url: str) -> str:
    """从 https://www.tiktok.com/@user/video/123... 提取作品 ID（视频或图片帖）。"""
    import re
    m = re.search(r"/(?:video|photo)/(\d{10,})", url or "")
    return m.group(1) if m else ""


def merge_friend_info(conversations: List["ChatCandidate"],
                      friends: List["ChatCandidate"]) -> int:
    """用好友 API 数据（uid→handle/sec_uid）就地补齐会话列表里的好友单聊项。

    会话列表 DOM 只有昵称 + conversation_id（含对端 uid），
    好友 API 才有 @用户名 / sec_uid。按对端 uid 关联补齐后，
    好友会话项在 UI 里能显示 @handle，采集校验也多一个判定 token。

    ⚠️ 名称也用 API 昵称覆盖：聊天头部显示的就是 API 昵称（探针验证），
    DOM 提取的名称可能被未读角标等干扰，校验必须以头部一致的数据为准。
    返回补齐的条数。
    """
    by_uid = {f.uid: f for f in friends or [] if f.uid}
    patched = 0
    for c in conversations or []:
        if c.chat_type != CHAT_TYPE_FRIEND or not c.uid:
            continue
        f = by_uid.get(c.uid)
        if f:
            changed = False
            if f.name and c.name != f.name:
                c.name = f.name
                changed = True
            if not c.handle and f.handle:
                c.handle = f.handle
                changed = True
            if not c.sec_uid and f.sec_uid:
                c.sec_uid = f.sec_uid
                changed = True
            if changed:
                patched += 1
    return patched
