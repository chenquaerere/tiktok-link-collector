"""DateResolver / DateValidator —— 作品发布时间解析与日期判定。

核心原则：宁可少采，不可错采。
- 仅当能可靠解析出绝对时间（ISO 8601 / epoch / 明确日期时间字符串）时，标记 CONFIRMED。
- 仅相对时间文本（"2h ago" / "Yesterday" / "昨天"）标记 RELATIVE_ONLY，不参与目标日期匹配。
- 无法解析标记 UNCONFIRMED，绝不默认成今天。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone as _dt_timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .models import DateConfidence

DEFAULT_TIMEZONE = "Asia/Shanghai"

# 无 tzdata 时的固定偏移降级（生产环境建议安装 tzdata 以获得夏令时正确性）
_FALLBACK_OFFSETS = {
    "Asia/Shanghai": 8,
    "Asia/Hong_Kong": 8,
    "Asia/Tokyo": 9,
    "Asia/Singapore": 8,
    "America/Los_Angeles": -8,
    "America/New_York": -5,
    "Europe/London": 0,
    "Europe/Paris": 1,
    "UTC": 0,
}


def _load_timezone(name: str):
    try:
        return ZoneInfo(name)
    except Exception:
        offset = _FALLBACK_OFFSETS.get(name)
        if offset is not None:
            return _dt_timezone(timedelta(hours=offset), name)
        return _dt_timezone.utc

# 绝对时间格式（无时区，按采集时区解释）
_ABSOLUTE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
)

# 相对时间正则 -> 单位。仅作 RELATIVE_ONLY 判定，不用于匹配目标日期。
_RELATIVE_PATTERNS = (
    (re.compile(r"just\s*now", re.I), "just_now"),
    (re.compile(r"刚刚"), "just_now"),
    (re.compile(r"(\d+)\s*(?:min(?:ute)?s?|m)\s*ago", re.I), "minutes"),
    (re.compile(r"(\d+)\s*(?:hour|hr|h)s?\s*ago", re.I), "hours"),
    (re.compile(r"(\d+)\s*(?:day|d)s?\s*ago", re.I), "days"),
    (re.compile(r"(\d+)\s*(?:week|wk|w)s?\s*ago", re.I), "weeks"),
    (re.compile(r"(\d+)\s*(?:month)s?\s*ago", re.I), "months"),
    (re.compile(r"yesterday", re.I), "yesterday"),
    (re.compile(r"昨天"), "yesterday"),
    (re.compile(r"(\d+)\s*秒前"), "seconds"),
    (re.compile(r"(\d+)\s*分钟前"), "minutes"),
    (re.compile(r"(\d+)\s*小时前"), "hours"),
    (re.compile(r"(\d+)\s*天前"), "days"),
    (re.compile(r"(\d+)\s*周前"), "weeks"),
    (re.compile(r"(\d+)\s*个月前"), "months"),
)


class DateResolution:
    __slots__ = ("dt", "confidence", "source")

    def __init__(self, dt: Optional[datetime], confidence: str, source: str):
        self.dt = dt
        self.confidence = confidence
        self.source = source

    @property
    def datetime_str(self) -> Optional[str]:
        return self.dt.strftime("%Y-%m-%d %H:%M:%S") if self.dt else None

    @property
    def date_str(self) -> Optional[str]:
        return self.dt.strftime("%Y-%m-%d") if self.dt else None

    @property
    def is_confirmed(self) -> bool:
        return self.confidence == DateConfidence.CONFIRMED.value

    def matches_date(self, target_date: str) -> bool:
        return self.is_confirmed and self.date_str == target_date


class DateResolver:
    def __init__(self, timezone: str = DEFAULT_TIMEZONE):
        self.timezone = timezone
        self.tz = _load_timezone(timezone)

    def resolve(self, raw: Any, reference: Optional[datetime] = None) -> DateResolution:
        ref = reference or datetime.now(self.tz)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=self.tz)

        if raw is None or raw == "":
            return DateResolution(None, DateConfidence.UNCONFIRMED.value, "empty")

        if isinstance(raw, datetime):
            dt = raw if raw.tzinfo else raw.replace(tzinfo=self.tz)
            return DateResolution(dt.astimezone(self.tz), DateConfidence.CONFIRMED.value, "datetime")

        if isinstance(raw, bool):
            return DateResolution(None, DateConfidence.UNCONFIRMED.value, "unknown")

        if isinstance(raw, (int, float)):
            dt = self._from_epoch(raw)
            if dt is None:
                return DateResolution(None, DateConfidence.UNCONFIRMED.value, "epoch_invalid")
            return DateResolution(dt, DateConfidence.CONFIRMED.value, "epoch")

        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return DateResolution(None, DateConfidence.UNCONFIRMED.value, "empty")

            iso = self._try_iso(s)
            if iso is not None:
                return DateResolution(iso, DateConfidence.CONFIRMED.value, "iso")

            absdt = self._try_absolute(s)
            if absdt is not None:
                return DateResolution(absdt, DateConfidence.CONFIRMED.value, "absolute")

            rel = self._try_relative(s, ref)
            if rel is not None:
                return DateResolution(rel[0], DateConfidence.RELATIVE_ONLY.value, f"relative:{rel[1]}")

        return DateResolution(None, DateConfidence.UNCONFIRMED.value, "unknown")

    # ---- helpers ----
    def _from_epoch(self, value) -> Optional[datetime]:
        try:
            ts = float(value)
        except (TypeError, ValueError):
            return None
        if ts <= 0:
            return None
        if ts > 1e12:  # 毫秒
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=self.tz)
        except (OverflowError, OSError, ValueError):
            return None

    def _try_iso(self, s: str) -> Optional[datetime]:
        t = s
        if t.endswith("Z") or t.endswith("z"):
            t = t[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(t)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)
        return dt.astimezone(self.tz)

    def _try_absolute(self, s: str) -> Optional[datetime]:
        for fmt in _ABSOLUTE_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
            except ValueError:
                continue
            return dt.replace(tzinfo=self.tz)
        return None

    def _try_relative(self, s: str, ref: datetime):
        for pattern, unit in _RELATIVE_PATTERNS:
            m = pattern.search(s)
            if not m:
                continue
            if unit == "just_now":
                return ref, "just_now"
            if unit == "yesterday":
                return ref - timedelta(days=1), "yesterday"
            n = int(m.group(1))
            delta = {
                "seconds": timedelta(seconds=n),
                "minutes": timedelta(minutes=n),
                "hours": timedelta(hours=n),
                "days": timedelta(days=n),
                "weeks": timedelta(weeks=n),
                "months": timedelta(days=30 * n),
            }.get(unit)
            return (ref - delta) if delta else None, unit
        return None
