"""任务恢复（断点续传）数据库层测试。"""
import os
import tempfile
import unittest

from app.core.models import Account
from app.db.database import Database


class TestTaskResume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp, "test.db"))

    def tearDown(self):
        self.db.close()

    def _acc(self, aid, uname):
        return Account(account_id=aid, username=uname,
                       profile_url=f"https://www.tiktok.com/@{uname}")

    def test_find_unfinished_task(self):
        self.db.insert_task("TASK-1", target_date="2026-09-24", status="running")
        self.db.insert_task("TASK-2", target_date="2026-09-24", status="completed")
        t = self.db.find_unfinished_task()
        self.assertIsNotNone(t)
        self.assertEqual(t["task_id"], "TASK-1")

    def test_unfinished_account_ids_excludes_completed(self):
        self.db.insert_task("TASK-1", target_date="2026-09-24", status="stopped")
        for aid, uname in [("a1", "A"), ("a2", "B"), ("a3", "C"), ("a4", "D")]:
            self.db.insert_account(self._acc(aid, uname))
        self.db.upsert_task_account("TASK-1", "a1", "A", 4, 4, "completed")
        self.db.upsert_task_account("TASK-1", "a2", "B", 4, 2, "partial")
        self.db.upsert_task_account("TASK-1", "a3", "C", 4, 0, "failed", "登录失效")
        self.db.upsert_task_account("TASK-1", "a4", "D", 4, 0, "skipped", "任务已停止")
        unfinished = self.db.unfinished_account_ids("TASK-1")
        self.assertIn("a3", unfinished)
        self.assertIn("a4", unfinished)
        self.assertNotIn("a1", unfinished)
        self.assertNotIn("a2", unfinished)

    def test_no_unfinished_when_all_done(self):
        self.db.insert_task("TASK-1", target_date="2026-09-24", status="stopped")
        for aid, uname in [("a1", "A"), ("a2", "B")]:
            self.db.insert_account(self._acc(aid, uname))
        self.db.upsert_task_account("TASK-1", "a1", "A", 4, 4, "completed")
        self.db.upsert_task_account("TASK-1", "a2", "B", 4, 0, "empty")
        self.assertEqual(self.db.unfinished_account_ids("TASK-1"), [])

    def test_resume_marks_completed_when_nothing_left(self):
        # 任务已停止但所有账号完成 → 无未完成，应可标记为完成
        self.db.insert_task("TASK-1", target_date="2026-09-24", status="stopped")
        self.db.insert_account(self._acc("a1", "A"))
        self.db.upsert_task_account("TASK-1", "a1", "A", 4, 4, "completed")
        self.assertEqual(self.db.unfinished_account_ids("TASK-1"), [])


if __name__ == "__main__":
    unittest.main()
