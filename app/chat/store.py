"""聊天模块持久化 DAO（chat_targets 最近目标 + chat_links 采集链接）。

独立于作品采集的 videos/collect_tasks 体系；仅复用 Database 连接与锁。
"""
from __future__ import annotations

from typing import List, Optional

from app.chat.models import CHAT_TYPE_FRIEND, ChatTarget
from app.db.database import Database


def _now_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ChatStore:
    def __init__(self, db: Database):
        self.db = db

    # ---- 最近使用目标 ----
    def upsert_target(self, target: ChatTarget) -> None:
        stable = target_stable_key(target)
        self.db.execute(
            "INSERT INTO chat_targets(stable_key, chat_type, name, handle, uid, sec_uid, "
            "conversation_id, last_used_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(stable_key) DO UPDATE SET chat_type=excluded.chat_type, "
            "name=excluded.name, handle=excluded.handle, uid=excluded.uid, "
            "sec_uid=excluded.sec_uid, conversation_id=excluded.conversation_id, "
            "last_used_at=excluded.last_used_at",
            (stable, target.chat_type, target.name, target.handle, target.uid,
             target.sec_uid, target.conversation_id, _now_str()),
        )

    def recent_targets(self, limit: int = 5) -> List[ChatTarget]:
        rows = self.db.query(
            "SELECT * FROM chat_targets ORDER BY last_used_at DESC LIMIT ?", (limit,))
        return [ChatTarget(
            chat_type=r["chat_type"], name=r["name"], conversation_id=r["conversation_id"],
            handle=r["handle"], uid=r["uid"], sec_uid=r["sec_uid"],
        ) for r in rows]

    # ---- 采集链接（替换式：同一目标重新采集按最后一次替换） ----
    def replace_links(self, stable_key: str, urls: List[str]) -> int:
        """替换式写入某目标的链接列表（按传入顺序 order 0..n）。"""
        with self.db.transaction():
            self.db.execute("DELETE FROM chat_links WHERE stable_key = ?", (stable_key,))
            for i, url in enumerate(urls):
                from app.chat.models import extract_video_id
                self.db.execute(
                    "INSERT OR IGNORE INTO chat_links(stable_key, video_id, video_url, "
                    "order_num, collected_at) VALUES(?,?,?,?,?)",
                    (stable_key, extract_video_id(url), url, i, _now_str()),
                )
        return len(urls)

    def links_for(self, stable_key: str) -> List[str]:
        rows = self.db.query(
            "SELECT video_url FROM chat_links WHERE stable_key = ? ORDER BY order_num",
            (stable_key,))
        return [r["video_url"] for r in rows]


def target_stable_key(target: ChatTarget) -> str:
    if target.conversation_id:
        return f"conv:{target.conversation_id}"
    if target.sec_uid:
        return f"secuid:{target.sec_uid}"
    return f"uid:{target.chat_type}:{target.uid}"
