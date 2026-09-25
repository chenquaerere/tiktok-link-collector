"""每日链接日志 DailyLinksLog 测试。"""
from __future__ import annotations

import os
import tempfile
import unittest

from app.log.daily_links import DailyLinksLog


class TestDailyLinksLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = DailyLinksLog(os.path.join(self.tmp, "links_log"))

    def test_filename_uses_yyyymmdd(self):
        self.assertEqual(DailyLinksLog.filename_for_date("2026-09-24"), "20260924.txt")
        self.assertEqual(DailyLinksLog.filename_for_date("20260924"), "20260924.txt")
        # 路径按年月日
        p = self.log.path_for("2026-09-24")
        self.assertTrue(p.endswith(os.path.join("links_log", "20260924.txt")), p)

    def test_append_and_load(self):
        u = "https://www.tiktok.com/@a/video/111"
        self.assertTrue(self.log.append(u, "2026-09-24"))
        self.assertEqual(self.log.load("2026-09-24"), [u])

    def test_dedup_same_day(self):
        u = "https://www.tiktok.com/@a/video/111"
        self.assertTrue(self.log.append(u, "2026-09-24"))
        self.assertFalse(self.log.append(u, "2026-09-24"))  # 重复跳过
        self.assertTrue(self.log.append("https://www.tiktok.com/@a/video/222", "2026-09-24"))
        self.assertEqual(len(self.log.load("2026-09-24")), 2)

    def test_different_days_separate_files(self):
        self.log.append("https://www.tiktok.com/@a/video/111", "2026-09-24")
        self.log.append("https://www.tiktok.com/@a/video/222", "2026-09-25")
        self.assertEqual(self.log.load("2026-09-24"), ["https://www.tiktok.com/@a/video/111"])
        self.assertEqual(self.log.load("2026-09-25"), ["https://www.tiktok.com/@a/video/222"])

    def test_append_many_returns_new_count(self):
        urls = ["https://www.tiktok.com/@a/video/1", "https://www.tiktok.com/@a/video/2"]
        self.assertEqual(self.log.append_many(urls, "2026-09-24"), 2)
        self.assertEqual(self.log.append_many(urls + ["https://www.tiktok.com/@a/video/3"],
                                              "2026-09-24"), 1)

    def test_empty_url_ignored(self):
        self.assertFalse(self.log.append("", "2026-09-24"))
        self.assertFalse(self.log.append("   ", "2026-09-24"))
        self.assertEqual(self.log.load("2026-09-24"), [])

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(self.log.load("2026-01-01"), [])

    def test_append_preserves_history(self):
        # 追加模式：同天多次采集只增新，不覆盖旧
        self.log.append("https://www.tiktok.com/@a/video/1", "2026-09-24")
        self.log.append("https://www.tiktok.com/@a/video/2", "2026-09-24")
        self.assertEqual(len(self.log.load("2026-09-24")), 2)
        # 行序保持
        self.assertEqual(self.log.load("2026-09-24"),
                         ["https://www.tiktok.com/@a/video/1",
                          "https://www.tiktok.com/@a/video/2"])


if __name__ == "__main__":
    unittest.main()
