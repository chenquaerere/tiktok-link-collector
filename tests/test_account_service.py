"""账号管理服务层测试：URL 解析、批量导入容错、增删改查。"""
from __future__ import annotations

import os
import tempfile
import unittest

from app.db.database import Database
from app.services.account_service import AccountService, parse_profile_url


class TestParseProfileUrl(unittest.TestCase):
    def test_full_url(self):
        r = parse_profile_url("https://www.tiktok.com/@demo_alpha")
        self.assertTrue(r.ok)
        self.assertEqual(r.username, "demo_alpha")
        self.assertEqual(r.profile_url, "https://www.tiktok.com/@demo_alpha")

    def test_url_with_query(self):
        r = parse_profile_url("https://www.tiktok.com/@demo_alpha?lang=en")
        self.assertTrue(r.ok)
        self.assertEqual(r.username, "demo_alpha")

    def test_handle(self):
        r = parse_profile_url("@demo_beta")
        self.assertTrue(r.ok)
        self.assertEqual(r.username, "demo_beta")

    def test_bare_username(self):
        r = parse_profile_url("demo_gamma")
        self.assertTrue(r.ok)
        self.assertEqual(r.username, "demo_gamma")

    def test_short_link_fails(self):
        r = parse_profile_url("https://vm.tiktok.com/ZMrAbc/")
        self.assertFalse(r.ok)

    def test_empty_fails(self):
        self.assertFalse(parse_profile_url("").ok)
        self.assertFalse(parse_profile_url("   ").ok)

    def test_illegal_chars_fail(self):
        self.assertFalse(parse_profile_url("hello world").ok)


class TestAccountService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp, "test.db"))
        self.svc = AccountService(self.db)

    def tearDown(self):
        self.db.close()

    def test_add(self):
        ok, msg = self.svc.add("https://www.tiktok.com/@demo_alpha")
        self.assertTrue(ok)
        self.assertEqual(self.db.count_accounts(), 1)

    def test_add_duplicate(self):
        self.svc.add("https://www.tiktok.com/@demo_alpha")
        ok, msg = self.svc.add("@demo_alpha")
        self.assertFalse(ok)
        self.assertEqual(self.db.count_accounts(), 1)

    def test_import_many_partial_failure(self):
        # 20 个里 2 个错误 → 18 个成功，不阻断
        raws = [f"https://www.tiktok.com/@user{i:02d}" for i in range(18)]
        raws += ["https://vm.tiktok.com/bad1/", "invalid input!!"]
        res = self.svc.import_many(raws)
        self.assertEqual(len(res["imported"]), 18)
        self.assertEqual(len(res["failed"]), 2)
        self.assertEqual(self.db.count_accounts(), 18)

    def test_import_many_internal_dedup(self):
        raws = ["https://www.tiktok.com/@dup", "@dup", "https://www.tiktok.com/@other"]
        res = self.svc.import_many(raws)
        self.assertEqual(len(res["imported"]), 2)
        self.assertEqual(len(res["skipped"]), 1)  # 内部重复

    def test_set_enabled(self):
        self.svc.add("@demo_alpha")
        self.assertTrue(self.svc.set_enabled("demo_alpha", False))
        row = self.svc.get("demo_alpha")
        self.assertEqual(row["enabled"], 0)

    def test_update_collect_count(self):
        self.svc.add("@demo_alpha")
        self.assertTrue(self.svc.update("demo_alpha", collect_count=8))
        self.assertEqual(self.svc.get("demo_alpha")["collect_count"], 8)

    def test_delete(self):
        self.svc.add("@demo_alpha")
        self.assertTrue(self.svc.delete("demo_alpha"))
        self.assertEqual(self.db.count_accounts(), 0)

    def test_list_enabled_only(self):
        self.svc.add("@a")
        self.svc.add("@b")
        self.svc.set_enabled("b", False)
        self.assertEqual(len(self.svc.list(enabled_only=True)), 1)


if __name__ == "__main__":
    unittest.main()
