"""基于 video_id 的内存去重器（配合数据库 UNIQUE(video_id) 实现持久化去重）。"""
from __future__ import annotations

from typing import Iterable, Optional


class VideoDedup:
    def __init__(self, initial: Optional[Iterable[str]] = None):
        self._seen = set(initial or [])

    def is_duplicate(self, video_id: str) -> bool:
        return video_id in self._seen

    def mark(self, video_id: str) -> None:
        self._seen.add(video_id)

    def mark_many(self, ids: Iterable[str]) -> None:
        self._seen.update(ids)

    def __len__(self) -> int:
        return len(self._seen)
