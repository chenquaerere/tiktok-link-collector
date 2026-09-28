"""CollectEngine 编排测试：最新N条、替换式记录、去重、数量限制、停止、恢复、失败隔离。

使用 MockCollector 模拟 ProfileCollector（真实浏览器在集成测试单独验证）。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.collector.engine import CollectEngine
from app.core.date_resolver import DateResolver
from app.core.models import Account, ParsedVideoItem
from app.db.database import Database
from tests.fixtures import (
    TODAY_09_24,
    YESTERDAY_09_23,
)

TARGET = "2026-09-24"


def _vid_item(video_id, create_time=None, username="demo_alpha"):
    return ParsedVideoItem(
        video_id=video_id,
        username=username,
        raw_url=f"https://www.tiktok.com/@{username}/video/{video_id}",
        raw_publish_time=create_time,
        time_source="epoch" if create_time is not None else "none",
    )


def _acc(aid, uname, count=4):
    return Account(account_id=aid, username=uname,
                   profile_url=f"https://www.tiktok.com/@{uname}",
                   collect_count=count)


class MockCollector:
    """模拟 ProfileCollector.collect(account, on_item) 接口。"""
    def __init__(self, items_by_account):
        self.items_by_account = items_by_account
        self.order = []  # 记录账号访问顺序（验证串行）

    def collect(self, account, on_item):
        self.order.append(account.username)
        items = self.items_by_account.get(account.username, [])
        for it in items:
            if not on_item(it):
                break
        return {
            "found": len(items),
            "scrolls": 1,
            "item_list_requests": 1,
            "create_times": [i.raw_publish_time for i in items if i.raw_publish_time is not None],
        }


def _today_items(count=4, username="demo_alpha", id_offset=0):
    ids = list(TODAY_09_24.keys())[:count]
    tms = list(TODAY_09_24.values())[:count]
    # id_offset 让不同账号拥有不同 video_id（TikTok video_id 全局唯一）
    return [_vid_item(str(int(v) + id_offset), t, username) for v, t in zip(ids, tms)]


def _yesterday_items(count=2, username="demo_alpha", id_offset=0):
    ids = list(YESTERDAY_09_23.keys())[:count]
    tms = list(YESTERDAY_09_23.values())[:count]
    return [_vid_item(str(int(v) + id_offset), t, username) for v, t in zip(ids, tms)]


class TestCollectEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp, "test.db"))

    def tearDown(self):
        self.db.close()

    def _engine(self, items_by_account, **kw):
        collector = MockCollector(items_by_account)
        resolver = DateResolver("Asia/Shanghai")
        return CollectEngine(self.db, collector, resolver, **kw)

    # ---- 最新N条规则（不过滤日期） ----
    def test_collects_latest_n_regardless_of_date(self):
        # 今天 4 + 昨天 2，要求 10 → 全采 6 条（含昨天）
        items = _today_items(4) + _yesterday_items(2)
        eng = self._engine({"demo_alpha": items})
        s = eng.run([_acc("a1", "demo_alpha", 10)], TARGET)
        self.assertEqual(s["new_videos"], 6)
        self.assertEqual(self.db.count_videos(), 6)
        dates = {r["publish_date"] for r in self.db.query("SELECT publish_date FROM videos")}
        self.assertIn(TARGET, dates)
        self.assertTrue(any(d and d < TARGET for d in dates))

    def test_no_works_returns_zero(self):
        eng = self._engine({"demo_alpha": []})
        s = eng.run([_acc("a1", "demo_alpha", 10)], TARGET)
        self.assertEqual(s["new_videos"], 0)
        self.assertEqual(self.db.count_videos(), 0)
        self.assertEqual(s["accounts"][0].status, "empty")

    def test_collect_count_limit(self):
        items = _today_items(4)
        eng = self._engine({"demo_alpha": items})
        s = eng.run([_acc("a1", "demo_alpha", 2)], TARGET)
        self.assertEqual(s["new_videos"], 2)
        self.assertEqual(self.db.count_videos(), 2)

    def test_unconfirmed_still_collected(self):
        # 新规定：无法确认日期的照常采集，publish_date 记空
        items = _today_items(3) + [_vid_item("9999999999999999999", None)]
        eng = self._engine({"demo_alpha": items})
        s = eng.run([_acc("a1", "demo_alpha", 10)], TARGET)
        self.assertEqual(s["new_videos"], 4)
        self.assertEqual(s["unconfirmed"], 1)
        row = self.db.query_one(
            "SELECT publish_date FROM videos WHERE video_id = ?",
            ("9999999999999999999",))
        self.assertIsNotNone(row)
        self.assertEqual(row["publish_date"], "")

    # ---- 去重 ----
    def test_video_id_unique_in_db(self):
        items = _today_items(4) + _today_items(4)  # 重复 4 条
        eng = self._engine({"demo_alpha": items})
        s = eng.run([_acc("a1", "demo_alpha", 10)], TARGET)
        self.assertEqual(s["new_videos"], 4)
        self.assertEqual(self.db.count_videos(), 4)  # DB 唯一

    # （原 test_rescan_discovers_new_videos 已被替换式记录用例取代）

    # ---- 替换式记录 ----
    def test_replace_deletes_old_videos(self):
        # 第一次：4 条 → 库 4 条
        eng = self._engine({"demo_alpha": _today_items(4)})
        eng.run([_acc("a1", "demo_alpha", 10)], TARGET)
        self.assertEqual(self.db.count_videos(), 4)
        # 第二次（同账号）：只有 2 条不同作品 → 按最后一次替换，库 2 条
        eng2 = self._engine({"demo_alpha": _today_items(2)})
        s2 = eng2.run([_acc("a1", "demo_alpha", 10)], TARGET, task_id="TASK-X")
        self.assertEqual(s2["new_videos"], 2)
        self.assertEqual(self.db.count_videos(), 2)  # 替换，不是累计 6

    def test_replace_only_affects_task_accounts(self):
        # 只采集 A 时，B 的历史记录不动
        engA = self._engine({"A": _today_items(2, "A", 0)})
        engA.run([_acc("a1", "A", 10)], TARGET)
        engB = self._engine({"B": _today_items(2, "B", 1000000)})
        engB.run([_acc("a2", "B", 10)], TARGET, task_id="TASK-B")
        self.assertEqual(self.db.count_videos(), 4)  # A(2) + B(2) 都在
        # 新任务只含 B → A 的 2 条保留，B 替换为 1 条
        engB2 = self._engine({"B": _today_items(1, "B", 2000000)})
        engB2.run([_acc("a2", "B", 10)], TARGET, task_id="TASK-B2")
        rows = self.db.query("SELECT account_id FROM videos")
        aids = sorted(r["account_id"] for r in rows)
        self.assertEqual(aids, ["a1", "a1", "a2"])

    # ---- 串行 & 失败隔离 ----
    # ---- 每次抓取都重新取最新 N 条（不得因历史记录跳过）----
    def test_rerun_returns_identical_newest_n(self):
        """★ 回归：库里已有记录时，重新抓取必须仍然拿到同样的最新 N 条。

        用户实测 bug（2026-09-24 有 40 条作品被标记「重复跳过」且从未入库）：
        旧实现把**全库已有 video_id** 装进去重器 → 重新抓取时最新作品被当成
        「重复」跳过 → 拿到的不是最新，或凑不够数量（用户回填时发现「少了两条链接」）。
        要求：不管之前采过没有，每次重新抓取都从最新一条开始取满数量。
        """
        items = _today_items(4)                 # 模拟主页最新的 4 条
        first = self._engine({"demo_alpha": items}).run(
            [_acc("a1", "demo_alpha", 4)], TARGET)
        ids_first = sorted(r["video_id"] for r in
                           self.db.query("SELECT video_id FROM videos"))
        self.assertEqual(first["new_videos"], 4)
        self.assertEqual(len(ids_first), 4)

        # 第二次抓取（同账号、主页内容不变）—— 结果必须完全一致
        second = self._engine({"demo_alpha": items}).run(
            [_acc("a1", "demo_alpha", 4)], TARGET)
        ids_second = sorted(r["video_id"] for r in
                            self.db.query("SELECT video_id FROM videos"))
        self.assertEqual(second["new_videos"], 4, "重新抓取不得因历史记录而少采")
        self.assertEqual(ids_second, ids_first, "两次抓取结果必须完全一致")
        self.assertEqual(second["accounts"][0].status, "completed")

    def test_newest_taken_even_when_older_rows_exist(self):
        """★ 回归：库里已有「更旧的作品」时，也必须优先拿最新那条（不能跳过最新）。"""
        # 第一次只采到昨天的 2 条（模拟历史记录）
        self._engine({"demo_alpha": _yesterday_items(2)}).run(
            [_acc("a1", "demo_alpha", 2)], TARGET)
        old_ids = {r["video_id"] for r in self.db.query("SELECT video_id FROM videos")}
        self.assertEqual(len(old_ids), 2)

        # 主页现在有了更新的今天作品 → 采集必须拿到今天的（最新），而不是跳过它们
        items = _today_items(2) + _yesterday_items(2)
        s = self._engine({"demo_alpha": items}).run([_acc("a1", "demo_alpha", 2)], TARGET)
        new_ids = [r["video_id"] for r in
                   self.db.query("SELECT video_id FROM videos ORDER BY id")]
        self.assertEqual(s["new_videos"], 2)
        self.assertTrue(set(new_ids).isdisjoint(old_ids),
                        "应替换为最新的今天作品，而不是跳过最新、保留旧的")
        self.assertEqual(set(new_ids), {i.video_id for i in _today_items(2)})

    def test_duplicate_within_profile_only_counted_once(self):
        """同一作品在主页列表里重复出现（置顶）时不占两个名额。

        注意：重复条目必须出现在「采满之前」—— 采满数量后采集器会立即停止
        （不继续滚动，这是期望的性能行为），因此末尾的重复不会被检查。
        """
        base = _today_items(4)
        items = [base[0]] + base                 # 第一条在开头再次出现 = 置顶作品
        s = self._engine({"demo_alpha": items}).run([_acc("a1", "demo_alpha", 4)], TARGET)
        self.assertEqual(s["new_videos"], 4, "4 条唯一作品都应采到")
        self.assertEqual(self.db.count_videos(), 4)
        d = s["accounts"][0].diagnostics
        self.assertEqual(d["duplicates"], 1, "重复条目应被识别并跳过")
        self.assertEqual({r["video_id"] for r in
                          self.db.query("SELECT video_id FROM videos")},
                         {i.video_id for i in base}, "入库的应是 4 条唯一作品")

    # ---- 昵称（display_name）----
    def test_nickname_written_during_collect(self):
        """★ 采集时顺手写入昵称（零额外请求），供账号管理页辨识账号。"""
        items = _today_items(2)
        for it in items:
            it.nickname = "我的昵称"
        self._engine({"demo_alpha": items}).run([_acc("a1", "demo_alpha", 2)], TARGET)
        self.assertEqual(self.db.get_account("a1")["display_name"], "我的昵称")

    def test_nickname_absent_keeps_existing(self):
        """取不到昵称时，不得覆盖账号已有的昵称。"""
        self.db.insert_account(_acc("a1", "demo_alpha", 2))
        self.db.set_account_display_name("a1", "原有昵称")
        self._engine({"demo_alpha": _today_items(2)}).run(
            [_acc("a1", "demo_alpha", 2)], TARGET)   # items 不带 nickname
        self.assertEqual(self.db.get_account("a1")["display_name"], "原有昵称")

    def test_strict_serial_order(self):
        collector = MockCollector({
            "A": _today_items(1, "A"),
            "B": _today_items(1, "B"),
            "C": _today_items(1, "C"),
        })
        eng = CollectEngine(self.db, collector, DateResolver("Asia/Shanghai"))
        eng.run([_acc("a1", "A"), _acc("a2", "B"), _acc("a3", "C")], TARGET)
        self.assertEqual(collector.order, ["A", "B", "C"])

    def test_single_account_failure_isolated(self):
        class FailingCollector(MockCollector):
            def collect(self, account, on_item):
                if account.username == "B":
                    raise RuntimeError("登录失效")
                return super().collect(account, on_item)

        collector = FailingCollector({
            "A": _today_items(2, "A", 0),
            "B": _today_items(2, "B", 1000000),
            "C": _today_items(2, "C", 2000000),
        })
        eng = CollectEngine(self.db, collector, DateResolver("Asia/Shanghai"))
        s = eng.run([_acc("a1", "A", 2), _acc("a2", "B", 2), _acc("a3", "C", 2)], TARGET)
        self.assertEqual(s["completed"], 2)   # A, C
        self.assertEqual(s["failed"], 1)      # B
        self.assertEqual(self.db.count_videos(), 4)  # A(2) + C(2)

    # ---- 停止 ----
    def test_stop_preserves_saved_data(self):
        eng = self._engine({"demo_alpha": _today_items(4)})
        results = {}

        def on_progress(idx, total, uname, status, detail):
            if uname == "demo_alpha" and status == "collecting" and detail.get("collected", 0) >= 2:
                eng.request_stop()

        eng.run([_acc("a1", "demo_alpha", 10)], TARGET, on_progress=on_progress)
        # 已入库的数据保留（>= 2 条）
        self.assertGreaterEqual(self.db.count_videos(), 2)

    # ---- 每账号独立数量 ----
    def test_per_account_collect_count(self):
        collector = MockCollector({
            "A": _today_items(4, "A", 0),
            "B": _today_items(4, "B", 1000000),
        })
        eng = CollectEngine(self.db, collector, DateResolver("Asia/Shanghai"))
        s = eng.run([_acc("a1", "A", 2), _acc("a2", "B", 4)], TARGET)
        by = {r.username: r for r in s["accounts"]}
        self.assertEqual(by["A"].actual_count, 2)
        self.assertEqual(by["B"].actual_count, 4)

    # ---- 每日链接日志集成（替换式） ----
    def test_daily_links_log_written(self):
        from app.log.daily_links import DailyLinksLog
        log = DailyLinksLog(os.path.join(self.tmp, "links_log"))
        eng = self._engine({"demo_alpha": _today_items(4)}, daily_links=log)
        eng.run([_acc("a1", "demo_alpha", 10)], TARGET)
        urls = log.load(TARGET)
        self.assertEqual(len(urls), 4)

    def test_daily_links_log_replaced_by_last_run(self):
        from app.log.daily_links import DailyLinksLog
        log = DailyLinksLog(os.path.join(self.tmp, "links_log"))
        # 第一次：4 条
        eng1 = self._engine({"demo_alpha": _today_items(4)}, daily_links=log)
        eng1.run([_acc("a1", "demo_alpha", 10)], TARGET)
        self.assertEqual(len(log.load(TARGET)), 4)
        # 第二次：只有 2 条 → 按最后一次替换，文件变为 2 条（不是累计 6）
        eng2 = self._engine({"demo_alpha": _today_items(2)}, daily_links=log)
        eng2.run([_acc("a1", "demo_alpha", 10)], TARGET, task_id="TASK-X")
        self.assertEqual(len(log.load(TARGET)), 2)


class TestPinnedItemsSkipped(unittest.TestCase):
    """置顶作品必须跳过、**不占「最新 N 条」名额**（2026-09-28 用户实测修复）。

    场景：主页列表 = [置顶(很旧), 新1, 新2, 新3]，采 3 条。
    修复前：拿到 [置顶, 新1, 新2] —— 少一条新发布的作品（用户实际遇到）。
    修复后：拿到 [新1, 新2, 新3]。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine_pin_")
        self.db = Database(os.path.join(self.tmp, "t.db"))

    def _run(self, listing, count=3):
        engine = CollectEngine(self.db, MockCollector({"demo_alpha": listing}),
                               DateResolver("Asia/Shanghai"))
        return engine.run([_acc("a1", "demo_alpha", count)], TARGET)

    @staticmethod
    def _pin(video_id, create_time):
        it = _vid_item(video_id, create_time, "demo_alpha")
        it.is_pinned = True
        return it

    def test_single_pinned_skipped_and_fills(self):
        items = _today_items(3, username="demo_alpha")
        listing = [self._pin("1111111111111111101", 1700000000)] + items
        s = self._run(listing, 3)
        videos = s["accounts"][0].videos
        self.assertEqual([v.video_id for v in videos], [i.video_id for i in items])
        self.assertEqual(s["accounts"][0].diagnostics["pinned_skipped"], 1)
        self.assertEqual(s["pinned_skipped"], 1)

    def test_three_pinned_all_skipped(self):
        """置顶上限 3 条时全部跳过，仍能取满 N 条。"""
        items = _today_items(3, username="demo_alpha")
        listing = [self._pin(f"22222222222222222{k:02d}", 1700000000 + k)
                   for k in range(3)] + items
        s = self._run(listing, 3)
        self.assertEqual([v.video_id for v in s["accounts"][0].videos],
                         [i.video_id for i in items])
        self.assertEqual(s["pinned_skipped"], 3)

    def test_no_pinned_behaviour_unchanged(self):
        items = _today_items(4, username="demo_alpha")
        s = self._run(items, 4)
        self.assertEqual(len(s["accounts"][0].videos), 4)
        self.assertEqual(s["pinned_skipped"], 0)

    def test_pinned_never_enters_database(self):
        items = _today_items(2, username="demo_alpha")
        pin = self._pin("3333333333333333301", 1700000000)
        self._run([pin] + items, 2)
        ids = {r["video_id"] for r in self.db.query("SELECT video_id FROM videos")}
        self.assertNotIn(pin.video_id, ids)
        self.assertEqual(len(ids), 2)


class TestRecentPinnedExtraCollected(unittest.TestCase):
    """置顶作品发布于「今天 / 昨天」时，应**额外采集**（不占「最新 N 条」名额）。

    用户规则（2026-09-28）：置顶作品的时间段是今天或者昨天，也把它拿下来；
    原本拿 3 条，判断置顶是今天/昨天后加起来就是 4 条。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="engine_recent_pin_")
        self.db = Database(os.path.join(self.tmp, "t.db"))
        self.tz = ZoneInfo("Asia/Shanghai")

    def _ts(self, days_ago=0, hours_ago=0):
        now = datetime.now(self.tz)
        return int((now - timedelta(days=days_ago, hours=hours_ago)).timestamp())

    @staticmethod
    def _items(n=3):
        """n 条非置顶作品（3 天前起，确保不落在「今天/昨天」）。"""
        return [_vid_item(f"50000000000000000{i}", 0, "demo_alpha") for i in range(n)]

    def _build_items(self, n=3):
        return [_vid_item(f"50000000000000000{i}", self._ts(days_ago=3 + i),
                          "demo_alpha") for i in range(n)]

    def _pin(self, vid, ts):
        it = _vid_item(vid, ts, "demo_alpha")
        it.is_pinned = True
        return it

    def _run(self, listing, count=3):
        engine = CollectEngine(self.db, MockCollector({"demo_alpha": listing}),
                               DateResolver("Asia/Shanghai"))
        return engine.run([_acc("a1", "demo_alpha", count)], TARGET)

    def test_today_pinned_extra_collected(self):
        items = self._build_items(3)
        pin = self._pin("5000000000000000901", self._ts(hours_ago=2))
        s = self._run([pin] + items, 3)
        r = s["accounts"][0]
        self.assertEqual(len(r.videos), 4, "3 条非置顶 + 1 条今天置顶 = 4 条")
        self.assertIn(pin.video_id, [v.video_id for v in r.videos])
        self.assertEqual(r.diagnostics["pinned_collected"], 1)
        self.assertEqual(r.diagnostics["pinned_skipped"], 0)
        self.assertEqual(s["pinned_collected"], 1)
        self.assertEqual(r.status, "completed")

    def test_yesterday_pinned_extra_collected(self):
        items = self._build_items(3)
        pin = self._pin("5000000000000000902", self._ts(days_ago=1, hours_ago=1))
        s = self._run([pin] + items, 3)
        r = s["accounts"][0]
        self.assertEqual(len(r.videos), 4)
        self.assertIn(pin.video_id, [v.video_id for v in r.videos])
        self.assertEqual(r.diagnostics["pinned_collected"], 1)

    def test_two_days_ago_pinned_still_skipped(self):
        """前天及更早的置顶 → 跳过，结果仍是 N 条。"""
        items = self._build_items(3)
        pin = self._pin("5000000000000000903", self._ts(days_ago=2, hours_ago=1))
        s = self._run([pin] + items, 3)
        r = s["accounts"][0]
        self.assertEqual(len(r.videos), 3)
        self.assertNotIn(pin.video_id, [v.video_id for v in r.videos])
        self.assertEqual(r.diagnostics["pinned_skipped"], 1)
        self.assertEqual(r.diagnostics["pinned_collected"], 0)

    def test_recent_pinned_does_not_consume_slot(self):
        """近期置顶不占名额：采 2 条非置顶 + 1 条近期置顶 = 3 条（而非 2 条）。"""
        items = self._build_items(2)
        pin = self._pin("5000000000000000904", self._ts(hours_ago=3))
        s = self._run([pin] + items, 2)
        r = s["accounts"][0]
        self.assertEqual(len(r.videos), 3)
        self.assertIn(pin.video_id, [v.video_id for v in r.videos])
        self.assertEqual(r.status, "completed")

    def test_recent_pinned_enters_database(self):
        items = self._build_items(2)
        pin = self._pin("5000000000000000905", self._ts(hours_ago=5))
        self._run([pin] + items, 2)
        ids = {r["video_id"] for r in self.db.query("SELECT video_id FROM videos")}
        self.assertIn(pin.video_id, ids)
        self.assertEqual(len(ids), 3)


if __name__ == "__main__":
    unittest.main()
