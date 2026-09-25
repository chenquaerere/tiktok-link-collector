"""DateResolver 单元测试：日期匹配 / 不匹配 / 无法确认 / 时区转换。"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.core.date_resolver import DateResolver
from app.core.models import DateConfidence


class TestDateResolver(unittest.TestCase):
    def setUp(self):
        self.r = DateResolver("Asia/Shanghai")

    # ---- 绝对时间（CONFIRMED） ----
    def test_iso_with_timezone(self):
        res = self.r.resolve("2026-09-24T18:30:00+08:00")
        self.assertEqual(res.confidence, DateConfidence.CONFIRMED.value)
        self.assertEqual(res.date_str, "2026-09-24")

    def test_iso_utc_converts_to_target_tz(self):
        # 2026-09-24 00:30 UTC = 08:30 Asia/Shanghai
        res = self.r.resolve("2026-09-24T00:30:00Z")
        self.assertEqual(res.datetime_str, "2026-09-24 08:30:00")
        self.assertEqual(res.date_str, "2026-09-24")

    def test_iso_naive_assumes_target_tz(self):
        res = self.r.resolve("2026-09-24 18:30:00")
        self.assertEqual(res.confidence, DateConfidence.CONFIRMED.value)
        self.assertEqual(res.datetime_str, "2026-09-24 18:30:00")

    def test_epoch_seconds(self):
        # 2026-09-24 18:30:00 +08:00
        ts = datetime(2026, 9, 24, 18, 30, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
        res = self.r.resolve(ts)
        self.assertEqual(res.date_str, "2026-09-24")

    def test_epoch_millis(self):
        ts = datetime(2026, 9, 24, 18, 30, 0, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000
        res = self.r.resolve(int(ts))
        self.assertEqual(res.date_str, "2026-09-24")

    def test_datetime_object(self):
        dt = datetime(2026, 9, 24, 10, 15, 0)
        res = self.r.resolve(dt)
        self.assertEqual(res.confidence, DateConfidence.CONFIRMED.value)

    # ---- 相对时间（RELATIVE_ONLY，不参与日期匹配） ----
    def test_relative_2h_ago_is_relative_only(self):
        res = self.r.resolve("2h ago")
        self.assertEqual(res.confidence, DateConfidence.RELATIVE_ONLY.value)
        self.assertFalse(res.is_confirmed)

    def test_relative_yesterday_is_relative_only(self):
        res = self.r.resolve("Yesterday")
        self.assertEqual(res.confidence, DateConfidence.RELATIVE_ONLY.value)

    def test_relative_chinese(self):
        self.assertEqual(self.r.resolve("刚刚").confidence, DateConfidence.RELATIVE_ONLY.value)
        self.assertEqual(self.r.resolve("3小时前").confidence, DateConfidence.RELATIVE_ONLY.value)

    # ---- 无法确认（UNCONFIRMED） ----
    def test_none_unconfirmed(self):
        self.assertEqual(self.r.resolve(None).confidence, DateConfidence.UNCONFIRMED.value)

    def test_empty_unconfirmed(self):
        self.assertEqual(self.r.resolve("").confidence, DateConfidence.UNCONFIRMED.value)

    def test_garbage_unconfirmed(self):
        self.assertEqual(self.r.resolve("???###").confidence, DateConfidence.UNCONFIRMED.value)

    # ---- 关键原则：不可靠日期绝不默认今天 ----
    def test_unconfirmed_never_defaults_to_today(self):
        for raw in [None, "", "2h ago", "Yesterday", "刚刚", "###"]:
            res = self.r.resolve(raw)
            self.assertFalse(res.matches_date("2026-09-24"), f"{raw!r} 不应被当作今天")

    def test_timezone_cross_day(self):
        # UTC 2026-09-23 18:30 = 上海 2026-09-24 02:30 → 属于 24 号
        r = DateResolver("Asia/Shanghai")
        res = r.resolve("2026-09-23T18:30:00Z")
        self.assertEqual(res.date_str, "2026-09-24")


if __name__ == "__main__":
    unittest.main()
