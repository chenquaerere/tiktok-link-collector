"""数据库层测试：表结构、索引、外键、WAL、事务、视频唯一性、账号池字段。"""
from __future__ import annotations

import os
import tempfile
import unittest

from app.core.models import Account, Video
from app.db.database import Database


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.tmp.name, "test.db"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    # ---- 结构 ----
    def test_tables_created(self):
        names = self.db.table_names()
        for t in ["accounts", "videos", "collect_tasks", "task_accounts", "collect_logs", "settings"]:
            self.assertIn(t, names)

    def test_indexes_exist(self):
        names = self.db.index_names()
        for idx in ["idx_videos_account", "idx_videos_publish_date",
                    "idx_videos_first_task", "idx_collect_logs_video"]:
            self.assertIn(idx, names)

    def test_foreign_keys_enabled(self):
        self.assertTrue(self.db.foreign_keys_enabled())

    def test_journal_mode_wal(self):
        self.assertEqual(self.db.journal_mode().lower(), "wal")

    # ---- 账号池 ----
    def test_account_fields(self):
        acc = Account(account_id="a1", username="demo_alpha",
                      profile_url="https://www.tiktok.com/@demo_alpha",
                      display_name="测试账号", remark="我的账号",
                      collect_count=8, last_collect_result="completed")
        self.assertTrue(self.db.insert_account(acc))
        row = self.db.get_account("a1")
        self.assertEqual(row["collect_count"], 8)
        self.assertEqual(row["last_collect_result"], "completed")
        self.assertEqual(row["username"], "demo_alpha")
        self.assertEqual(row["display_name"], "测试账号")

    def test_account_profile_url_unique(self):
        a = Account(account_id="a1", username="u1", profile_url="https://www.tiktok.com/@u1")
        b = Account(account_id="a2", username="u2", profile_url="https://www.tiktok.com/@u1")
        self.assertTrue(self.db.insert_account(a))
        self.assertFalse(self.db.insert_account(b))  # 重复 profile_url 被唯一约束忽略
        self.assertEqual(self.db.count_accounts(), 1)

    # ---- 视频唯一性 ----
    def test_video_unique_and_first_collect_time(self):
        self.db.insert_account(Account(account_id="a1", username="u1",
                                       profile_url="https://www.tiktok.com/@u1"))
        v = Video(video_id="111", account_id="a1", username="u1", video_url="https://x/111")
        self.assertTrue(self.db.insert_video(v))
        row = self.db.query_one("SELECT * FROM videos WHERE video_id='111'")
        self.assertTrue(row["first_collect_time"])  # 首次采集时间已记录
        self.assertFalse(self.db.insert_video(v))   # 重复插入被忽略
        self.assertEqual(self.db.count_videos(), 1)

    def test_video_exists(self):
        self.db.insert_account(Account(account_id="a1", username="u1",
                                       profile_url="https://www.tiktok.com/@u1"))
        self.db.insert_video(Video(video_id="111", account_id="a1", username="u1", video_url="https://x/111"))
        self.assertTrue(self.db.video_exists("111"))
        self.assertFalse(self.db.video_exists("999"))

    def test_load_all_video_ids(self):
        self.db.insert_account(Account(account_id="a1", username="u1",
                                       profile_url="https://www.tiktok.com/@u1"))
        self.db.insert_video(Video(video_id="111", account_id="a1", username="u1", video_url="https://x/111"))
        self.db.insert_video(Video(video_id="222", account_id="a1", username="u1", video_url="https://x/222"))
        self.assertEqual(set(self.db.load_all_video_ids()), {"111", "222"})

    # ---- 外键级联 ----
    def test_delete_account_cascades_videos(self):
        self.db.insert_account(Account(account_id="a1", username="u1",
                                       profile_url="https://www.tiktok.com/@u1"))
        self.db.insert_video(Video(video_id="111", account_id="a1", username="u1", video_url="https://x/111"))
        self.db.execute("DELETE FROM accounts WHERE account_id='a1'")
        self.assertEqual(self.db.count_videos(), 0)  # 级联删除作品

    def test_delete_task_keeps_video(self):
        self.db.insert_account(Account(account_id="a1", username="u1",
                                       profile_url="https://www.tiktok.com/@u1"))
        self.db.insert_task("TASK-1")
        self.db.insert_video(Video(video_id="111", account_id="a1", username="u1",
                                   video_url="https://x/111", first_task_id="TASK-1"))
        self.db.execute("DELETE FROM collect_tasks WHERE task_id='TASK-1'")
        # 删除任务保留作品，first_task_id 置 NULL
        self.assertEqual(self.db.count_videos(), 1)
        row = self.db.query_one("SELECT first_task_id FROM videos WHERE video_id='111'")
        self.assertIsNone(row["first_task_id"])

    # ---- 事务 ----
    def test_transaction_rollback(self):
        try:
            with self.db.transaction():
                self.db.insert_account(Account(account_id="a1", username="u1",
                                               profile_url="https://www.tiktok.com/@u1"))
                self.db.insert_video(Video(video_id="111", account_id="a1", username="u1",
                                           video_url="https://x/111"))
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertEqual(self.db.count_accounts(), 0)
        self.assertEqual(self.db.count_videos(), 0)

    def test_transaction_commit(self):
        with self.db.transaction():
            self.db.insert_account(Account(account_id="a1", username="u1",
                                           profile_url="https://www.tiktok.com/@u1"))
        self.assertEqual(self.db.count_accounts(), 1)

    # ---- 日志 ----
    def test_insert_collect_log(self):
        self.db.insert_account(Account(account_id="a1", username="u1",
                                       profile_url="https://www.tiktok.com/@u1"))
        self.db.insert_task("TASK-1")
        self.db.insert_collect_log("TASK-1", "a1", "已存在，去重跳过", video_id="111")
        rows = self.db.query("SELECT * FROM collect_logs WHERE video_id='111'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["message"], "已存在，去重跳过")

    # ---- settings ----
    def test_settings_get_set(self):
        self.assertIsNone(self.db.get_setting("k"))
        self.db.set_setting("k", "v")
        self.assertEqual(self.db.get_setting("k"), "v")
        self.db.set_setting("k", "v2")
        self.assertEqual(self.db.get_setting("k"), "v2")


if __name__ == "__main__":
    unittest.main()
