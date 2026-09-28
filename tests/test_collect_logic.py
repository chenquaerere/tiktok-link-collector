"""核心采集逻辑测试（2026-09-25 新语义：最新N条、不过滤日期、无法确认照常采集）。

场景：
- A: 今天 4 条 + 昨天 5 条（时间倒序）
- B: 今天 2 条
- C: 仅昨天 5 条
- D: 今天 4 条，其中 1 条日期无法确认
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.collect_logic import collect_for_account
from app.core.date_resolver import DateResolver
from app.core.dedup import VideoDedup
from mocks.mock_provider import MockTikTokProvider, make_account

TARGET = "2026-09-24"


def _collect(scenario, count=4, dedup=None):
    provider = MockTikTokProvider(TARGET)
    items = provider.fetch(scenario)
    acc = make_account(f"acc_{scenario}", f"user_{scenario}", scenario, count)
    resolver = DateResolver("Asia/Shanghai")
    dedup = dedup if dedup is not None else VideoDedup()
    return collect_for_account(
        items, target_date=TARGET, target_count=count,
        account_id=acc.account_id, username=acc.username,
        resolver=resolver, dedup=dedup,
    )


class TestCollectLogic(unittest.TestCase):
    def test_A_latest_4_are_today(self):
        # A 场景时间倒序，前 4 条恰好是今天的
        r = _collect("A", count=4)
        self.assertEqual(r.actual_count, 4)
        self.assertEqual(r.status, "completed")
        self.assertTrue(all(v.publish_date == TARGET for v in r.videos))

    def test_A_quantity_limit_2(self):
        r = _collect("A", count=2)
        self.assertEqual(r.actual_count, 2)
        self.assertEqual(len(r.videos), 2)

    def test_A_fills_with_older_when_count_exceeds(self):
        # 新规定：不过滤日期，要求 10 条但只有 9 条 → 全采 9 条（含昨天）
        r = _collect("A", count=10)
        self.assertEqual(r.actual_count, 9)
        self.assertEqual(r.status, "partial")
        dates = {v.publish_date for v in r.videos}
        self.assertIn(TARGET, dates)
        self.assertTrue(any(d < TARGET for d in dates))  # 包含更早作品

    def test_B_insufficient(self):
        r = _collect("B", count=4)
        self.assertEqual(r.actual_count, 2)
        self.assertEqual(r.status, "partial")
        self.assertEqual(r.diagnostics["collected"], 2)

    def test_C_older_works_collected(self):
        # 新规定：昨天/更早作品照常采集
        r = _collect("C", count=4)
        self.assertEqual(r.actual_count, 4)
        self.assertEqual(r.status, "completed")
        self.assertTrue(all(v.publish_date < TARGET for v in r.videos))

    def test_D_unconfirmed_still_collected(self):
        # 新规定：无法确认日期的照常采集，publish_date 记空
        r = _collect("D", count=4)
        self.assertEqual(r.actual_count, 4)
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.diagnostics["date_unconfirmed"], 1)
        blank = [v for v in r.videos if not v.publish_date]
        self.assertEqual(len(blank), 1)

    def test_duplicate_video_only_once(self):
        provider = MockTikTokProvider(TARGET)
        items = provider.fetch("A")[:4]  # 今天 4 条
        items = items + items[:1]  # 第一条重复出现
        dedup = VideoDedup()
        resolver = DateResolver("Asia/Shanghai")
        r = collect_for_account(
            items, target_date=TARGET, target_count=5,
            account_id="acc_A", username="user_A",
            resolver=resolver, dedup=dedup,
        )
        self.assertEqual(r.actual_count, 4)  # 列表里只有 4 条唯一作品
        self.assertEqual(r.diagnostics["duplicates"], 1)

    def test_url_normalized_in_result(self):
        r = _collect("A", count=4)
        self.assertEqual(r.videos[0].video_url, "https://www.tiktok.com/@user_A/video/101")

    def test_multi_account_counts(self):
        expected = {"A": 4, "B": 2, "C": 4, "D": 4}
        for scenario, n in expected.items():
            r = _collect(scenario, count=4)
            self.assertEqual(r.actual_count, n, f"账号 {scenario} 数量错误")

    def test_diagnostics_explain_why(self):
        r = _collect("A", count=4)
        d = r.diagnostics
        self.assertEqual(d["found"], 5)        # 采满 4 条后停（含第 5 条的检查）
        self.assertEqual(d["collected"], 4)    # 最新 4 条
        self.assertEqual(d["date_resolved"], 4)


class TestPinnedSkipped(unittest.TestCase):
    """批量入口 collect_for_account 同样跳过置顶（与 engine._collect_once 行为一致）。"""

    @staticmethod
    def _mk(vid, ct, pinned=False):
        from app.core.models import ParsedVideoItem
        return ParsedVideoItem(
            video_id=vid, username="u",
            raw_url=f"https://www.tiktok.com/@u/video/{vid}",
            raw_publish_time=ct, time_source="epoch", is_pinned=pinned)

    def test_pinned_not_selected(self):
        items = [self._mk("7000000000000000101", 1790200000, True),   # 置顶（旧）
                 self._mk("7000000000000000102", 1790200100),
                 self._mk("7000000000000000103", 1790200200)]
        r = collect_for_account(items, target_date="2026-09-24", target_count=2,
                                account_id="a1", username="u",
                                resolver=DateResolver("Asia/Shanghai"),
                                dedup=VideoDedup())
        self.assertEqual([v.video_id for v in r.videos],
                         ["7000000000000000102", "7000000000000000103"])
        self.assertEqual(r.diagnostics["pinned_skipped"], 1)
        self.assertEqual(r.actual_count, 2)

    def test_no_pinned_unchanged(self):
        items = [self._mk("7000000000000000201", 1790200000),
                 self._mk("7000000000000000202", 1790200100)]
        r = collect_for_account(items, target_date="2026-09-24", target_count=2,
                                account_id="a1", username="u",
                                resolver=DateResolver("Asia/Shanghai"),
                                dedup=VideoDedup())
        self.assertEqual(len(r.videos), 2)
        self.assertEqual(r.diagnostics["pinned_skipped"], 0)


class TestRecentPinnedExtraBatch(unittest.TestCase):
    """批量入口 collect_for_account：近期置顶额外采集（与 engine 行为一致）。"""

    tz = ZoneInfo("Asia/Shanghai")

    @classmethod
    def _ts(cls, days_ago=0, hours_ago=0):
        now = datetime.now(cls.tz)
        return int((now - timedelta(days=days_ago, hours=hours_ago)).timestamp())

    @classmethod
    def _mk(cls, vid, ct, pinned=False):
        from app.core.models import ParsedVideoItem
        return ParsedVideoItem(
            video_id=vid, username="u",
            raw_url=f"https://www.tiktok.com/@u/video/{vid}",
            raw_publish_time=ct, time_source="epoch", is_pinned=pinned)

    def _run(self, items, count):
        return collect_for_account(items, target_date="2026-09-28", target_count=count,
                                   account_id="a1", username="u",
                                   resolver=DateResolver("Asia/Shanghai"),
                                   dedup=VideoDedup())

    def test_today_pinned_extra(self):
        items = [self._mk("6000000000000000001", self._ts(hours_ago=2), True),
                 self._mk("6000000000000000002", self._ts(days_ago=3)),
                 self._mk("6000000000000000003", self._ts(days_ago=4))]
        r = self._run(items, 2)
        self.assertEqual(len(r.videos), 3, "2 条非置顶 + 1 条今天置顶 = 3 条")
        self.assertEqual(r.diagnostics["pinned_collected"], 1)
        self.assertEqual(r.actual_count, 3)

    def test_old_pinned_skipped(self):
        items = [self._mk("6000000000000000011", self._ts(days_ago=5), True),
                 self._mk("6000000000000000012", self._ts(days_ago=3)),
                 self._mk("6000000000000000013", self._ts(days_ago=4))]
        r = self._run(items, 2)
        self.assertEqual(len(r.videos), 2)
        self.assertEqual(r.diagnostics["pinned_skipped"], 1)
        self.assertEqual(r.diagnostics["pinned_collected"], 0)


if __name__ == "__main__":
    unittest.main()
