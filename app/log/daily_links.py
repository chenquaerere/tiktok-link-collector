"""每日链接日志（DailyLinksLog）。

把每天采集下来的作品链接，按日期归档到纯文本文件，文件按「年月日」命名，
例如 `20260924.txt`。

设计要点：
- 文件名 = 采集日期（YYYYMMDD），默认当天，可显式传入日期。
- 内容 = 每行一个规范化作品 URL（纯 URL，方便直接复制）。
- 同一天内自动去重：同一个 video_id/URL 只写一行，不重复追加。
- 记录规则（2026-09-25 用户规定）：同日多次采集按「最后一次运行」整体替换
  （replace）；append 仍保留供增量场景使用。
- UTF-8 编码，兼容中文备注/账号名。
"""
from __future__ import annotations

import os
import threading
from datetime import date, datetime
from typing import Iterable, List, Optional


class DailyLinksLog:
    """按日期归档作品链接的纯文本日志。

    线程安全（内部锁），可在采集引擎的多线程/回调中安全调用。
    """

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self._lock = threading.Lock()

    # ---- 路径 ----
    def _resolve_dir(self) -> str:
        return self.base_dir

    def _path_for_date(self, day: str) -> str:
        """返回某日期（YYYYMMDD 或 YYYY-MM-DD）对应的文件路径。"""
        norm = day.replace("-", "")[:8]
        return os.path.join(self._resolve_dir(), f"{norm}.txt")

    def path_for(self, day: Optional[str] = None) -> str:
        """返回当天（或指定日期）的链接日志文件路径。"""
        return self._path_for_date(day or self._today())

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y%m%d")

    @staticmethod
    def _date_of(dt: datetime) -> str:
        return dt.strftime("%Y%m%d")

    # ---- 读取 ----
    def load(self, day: Optional[str] = None) -> List[str]:
        """读取某日已归档的链接列表（按文件行序）。"""
        path = self.path_for(day)
        with self._lock:
            if not os.path.exists(path):
                return []
            with open(path, "r", encoding="utf-8") as f:
                return [line.rstrip("\n").rstrip("\r") for line in f if line.strip()]

    def load_urls(self, day: Optional[str] = None) -> List[str]:
        return self.load(day)

    # ---- 写入（去重追加）----
    def append(self, url: str, day: Optional[str] = None) -> bool:
        """追加一条 URL。已存在则跳过并返回 False，真正写入返回 True。"""
        url = (url or "").strip()
        if not url:
            return False
        path = self.path_for(day)
        with self._lock:
            os.makedirs(self._resolve_dir(), exist_ok=True)
            existing = set()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    existing = {ln.strip() for ln in f if ln.strip()}
            if url in existing:
                return False
            with open(path, "a", encoding="utf-8") as f:
                f.write(url + "\n")
            return True

    def append_many(self, urls: Iterable[str], day: Optional[str] = None) -> int:
        """批量追加，返回真正新增的行数。"""
        return sum(1 for u in urls if self.append(u, day))

    def replace(self, urls: Iterable[str], day: Optional[str] = None) -> int:
        """整体替换某日文件内容（按「最后一次运行」替换的记录规则）。

        去重、保持顺序；返回写入条数。
        """
        seen: set = set()
        ordered: List[str] = []
        for u in urls:
            u = (u or "").strip()
            if u and u not in seen:
                seen.add(u)
                ordered.append(u)
        path = self.path_for(day)
        with self._lock:
            os.makedirs(self._resolve_dir(), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                for u in ordered:
                    f.write(u + "\n")
        return len(ordered)

    def contains(self, url: str, day: Optional[str] = None) -> bool:
        url = (url or "").strip()
        return url in set(self.load(day))

    # ---- 日期解析辅助 ----
    @classmethod
    def filename_for_date(cls, day: Optional[str] = None) -> str:
        """返回「年月日」命名：YYYYMMDD.txt。"""
        norm = (day or cls._today()).replace("-", "")[:8]
        return f"{norm}.txt"
