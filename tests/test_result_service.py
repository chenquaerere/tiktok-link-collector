"""结果 / 复制 / 历史服务层测试。"""
from __future__ import annotations

import os
import tempfile
import unittest

from app.core.models import Video
from app.db.database import Database
from app.services.result_service import ResultService


def _video(vid, uname, date, url):
    return Video(video_id=vid, account_id=uname, username=uname, video_url=url,
                 publish_time=f"{date} 12:00:00", publish_date=date,
                 first_task_id="TASK-20260924-001")


class TestResultService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp, "test.db"))
        self.svc = ResultService(self.db)
        # 预置账号与任务（外键依赖）
        for u in ["a", "b"]:
            from app.core.models import Account
            self.db.insert_account(Account(account_id=u, username=u,
                                           profile_url=f"https://www.tiktok.com/@{u}"))
        self.db.insert_task("TASK-20260924-001", target_date="2026-09-24")

    def tearDown(self):
        self.db.close()

    def _seed(self):
        self.db.insert_video(_video("1", "a", "2026-09-24", "https://www.tiktok.com/@a/video/1"))
        self.db.insert_video(_video("2", "a", "2026-09-24", "https://www.tiktok.com/@a/video/2"))
        self.db.insert_video(_video("3", "b", "2026-09-24", "https://www.tiktok.com/@b/video/3"))
        self.db.insert_video(_video("4", "a", "2026-09-23", "https://www.tiktok.com/@a/video/4"))

    def test_query_by_date(self):
        self._seed()
        rows = self.svc.query_videos(publish_date="2026-09-24")
        self.assertEqual(len(rows), 3)

    def test_query_by_account(self):
        self._seed()
        rows = self.svc.query_videos(account_id="a")
        self.assertEqual(len(rows), 3)

    def test_query_by_task(self):
        self._seed()
        rows = self.svc.query_videos(task_id="TASK-20260924-001")
        self.assertEqual(len(rows), 4)

    def test_to_url_text(self):
        self._seed()
        rows = self.svc.query_videos(publish_date="2026-09-24")
        text = self.svc.to_url_text(rows)
        urls = [u for u in text.split("\n") if u.strip()]
        self.assertEqual(len(urls), 3)
        self.assertTrue(all(u.startswith("https://www.tiktok.com/") for u in urls))
        # 空行分隔：每条链接之间应有空行
        self.assertIn("\n\n", text)

    def test_to_url_text_dedup(self):
        self._seed()
        # 构造重复行
        rows = list(self.svc.query_videos(account_id="a")) * 2
        text = self.svc.to_url_text(rows)
        urls = [u for u in text.split("\n") if u.strip()]
        self.assertEqual(len(urls), 3)  # 去重后 a 账号 3 条

    def test_grouped_text(self):
        self._seed()
        rows = self.svc.query_videos(publish_date="2026-09-24")
        text = self.svc.to_grouped_text(rows)
        self.assertIn("@a", text)
        self.assertIn("@b", text)
        self.assertIn("https://www.tiktok.com/@a/video/1", text)

    def test_account_stats(self):
        self._seed()
        rows = self.svc.query_videos(publish_date="2026-09-24")
        stats = self.svc.account_stats(rows)
        by = {s["username"]: s for s in stats}
        self.assertEqual(by["a"]["actual_count"], 2)
        self.assertEqual(by["b"]["actual_count"], 1)

    def test_task_detail(self):
        self.db.insert_task("TASK-20260924-001", target_date="2026-09-24")
        self._seed()
        d = self.svc.task_detail("TASK-20260924-001")
        self.assertIsNotNone(d["task"])
        self.assertEqual(len(d["videos"]), 4)

    def test_date_video_urls(self):
        self._seed()
        text = self.svc.date_video_urls("2026-09-24")
        urls = [u for u in text.split("\n") if u.strip()]
        self.assertEqual(len(urls), 3)


if __name__ == "__main__":
    unittest.main()
