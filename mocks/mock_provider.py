"""Mock TikTok 主页数据源，开发阶段替代真实浏览器访问。

场景（对应需求 §27）：
- A: 今天 4 条 + 昨天 5 条
- B: 今天 2 条（当日不足）
- C: 今天 0 条（仅昨天 5 条）
- D: 今天 4 条，其中 1 条日期无法确认
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from app.core.models import ParsedVideoItem


def _dt(date_str: str, time_str: str) -> str:
    return f"{date_str} {time_str}"


class MockTikTokProvider:
    def __init__(self, target_date: str):
        self.target_date = target_date
        self.yesterday = self._shift(target_date, -1)

    @staticmethod
    def _shift(date_str: str, days: int) -> str:
        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
        return d.strftime("%Y-%m-%d")

    def _make(self, username: str, video_id: str, date_str: str, time_str: str,
              confirmed: bool = True) -> ParsedVideoItem:
        item = ParsedVideoItem(
            video_id=video_id,
            username=username,
            raw_url=f"https://www.tiktok.com/@{username}/video/{video_id}",
        )
        if confirmed:
            item.raw_publish_time = _dt(date_str, time_str)
            item.time_source = "absolute"
        else:
            # 无法确认：仅有相对时间文本（规范禁止仅依赖相对时间）
            item.raw_publish_time = "2h ago"
            item.time_source = "relative"
        return item

    def fetch(self, scenario: str) -> List[ParsedVideoItem]:
        t = self.target_date
        y = self.yesterday
        u = f"user_{scenario}"

        if scenario == "A":
            today = [("18:30:00", "101"), ("15:20:00", "102"), ("10:15:00", "103"), ("08:30:00", "104")]
            yest = [("22:10:00", "105"), ("19:20:00", "106"), ("16:00:00", "107"), ("12:30:00", "108"), ("09:00:00", "109")]
            items = [self._make(u, vid, t, tm) for tm, vid in today]
            items += [self._make(u, vid, y, tm) for tm, vid in yest]
            return items

        if scenario == "B":
            today = [("18:30:00", "201"), ("15:20:00", "202")]
            return [self._make(u, vid, t, tm) for tm, vid in today]

        if scenario == "C":
            yest = [("22:10:00", "301"), ("19:20:00", "302"), ("16:00:00", "303"), ("12:30:00", "304"), ("09:00:00", "305")]
            return [self._make(u, vid, y, tm) for tm, vid in yest]

        if scenario == "D":
            # 第 3 条（10:15）无法确认日期
            today = [
                ("18:30:00", "401", True),
                ("15:20:00", "402", True),
                ("10:15:00", "403", False),
                ("08:30:00", "404", True),
            ]
            return [self._make(u, vid, t, tm, confirmed=conf) for tm, vid, conf in today]

        if scenario == "E":
            # 今天 4 条（用于测试多账号中第二个"完成"账号，id 独立避免与 A 去重冲突）
            today = [("18:30:00", "501"), ("15:20:00", "502"), ("10:15:00", "503"), ("08:30:00", "504")]
            return [self._make(u, vid, t, tm) for tm, vid in today]

        return []


def make_account(account_id: str, username: str, scenario: str, count: int = 4) -> object:
    """构造 Account（供测试与 TaskRunner 使用）。"""
    from app.core.models import Account
    return Account(
        account_id=account_id,
        username=username,
        profile_url=f"https://www.tiktok.com/@{username}",
        collect_count=count,
    )
