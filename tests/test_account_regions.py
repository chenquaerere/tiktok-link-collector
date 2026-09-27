"""账号地区分类测试（含「旧库增量升级不丢数据」核心回归）。"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from app.core import regions as region_util
from app.db.database import Database, SCHEMA_VERSION
from app.services.account_service import AccountService

# 旧版 accounts 表定义（**没有 region 列**）—— 用于验证增量迁移
_LEGACY_ACCOUNTS = """
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    profile_url TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    remark TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    login_status TEXT NOT NULL DEFAULT 'unknown',
    collect_count INTEGER NOT NULL DEFAULT 4,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    last_collect_time TEXT,
    last_collect_result TEXT NOT NULL DEFAULT ''
);
"""


def _tmp_db_path(name: str = "t.db") -> str:
    return os.path.join(tempfile.mkdtemp(prefix="region_"), name)


def _make_legacy_db(path: str, rows=(("a1", "legacy_one"), ("a2", "legacy_two"))) -> None:
    """造一个「老版本」库：user_version 相同、accounts 无 region 列、已有账号数据。"""
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_ACCOUNTS)
    for aid, uname in rows:
        conn.execute(
            "INSERT INTO accounts(account_id, username, profile_url) VALUES(?,?,?)",
            (aid, uname, f"https://www.tiktok.com/@{uname}"))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.close()


class TestLegacyUpgradeKeepsData(unittest.TestCase):
    """★ 核心回归：加字段绝不能让用户数据丢失。

    背景：`Database._migrate()` 在 `user_version != SCHEMA_VERSION` 时会
    **DROP 所有业务表并重建**。因此「加字段」不能靠递增版本号，
    必须走 `_ensure_columns()` 的 ALTER TABLE 增量补列。
    """

    def test_columns_added_and_rows_preserved(self):
        path = _tmp_db_path()
        _make_legacy_db(path)
        db = Database(path)
        rows = db.list_accounts()
        self.assertEqual(len(rows), 2, "旧账号数据必须保留")
        self.assertEqual({r["username"] for r in rows}, {"legacy_one", "legacy_two"})
        for r in rows:
            self.assertEqual(r["region"], "", "新列默认应为空串")
        # 版本号保持不变 —— 一旦被改，上面的分支会清空用户库
        self.assertEqual(db.query_one("PRAGMA user_version")[0], SCHEMA_VERSION)
        db.close()

    def test_upgrade_is_idempotent(self):
        """重复打开不得重复加列或报错。"""
        path = _tmp_db_path()
        _make_legacy_db(path)
        for _ in range(3):
            db = Database(path)
            self.assertEqual(len(db.list_accounts()), 2)
            db.close()

    def test_region_survives_collect_count_edit(self):
        """★ 回归：改采集数量不得把地区清空（update_account 是整行覆盖式 UPDATE）。"""
        path = _tmp_db_path()
        _make_legacy_db(path)
        db = Database(path)
        svc = AccountService(db)
        svc.set_regions(["a1"], "越南")
        svc.update("a1", collect_count=9)
        row = db.get_account("a1")
        self.assertEqual(row["collect_count"], 9)
        self.assertEqual(row["region"], "越南")
        db.close()


class TestRegionHelpers(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(region_util.normalize_region("  越南 "), "越南")
        self.assertEqual(region_util.normalize_region("未分类"), "")
        self.assertEqual(region_util.normalize_region(None), "")
        self.assertEqual(region_util.normalize_region("全部地区"), "")

    def test_display(self):
        self.assertEqual(region_util.region_display(""), "未分类")
        self.assertEqual(region_util.region_display("缅甸"), "缅甸")

    def test_presets_contain_required_regions(self):
        """用户明确要求：必须有越南、缅甸。"""
        self.assertIn("越南", region_util.REGIONS)
        self.assertIn("缅甸", region_util.REGIONS)

    def test_label_with_and_without_region(self):
        self.assertEqual(
            region_util.account_label({"username": "u1", "region": "越南"}),
            "越南 · @u1")
        self.assertEqual(
            region_util.account_label({"username": "u1", "region": ""}), "@u1")

    def test_label_roundtrip(self):
        """显示名必须能反解回 account_id（三个页面靠它回查账号）。"""
        for region in ("越南", "缅甸", "印度尼西亚", ""):
            row = {"username": "demo.user-1", "region": region}
            self.assertEqual(
                region_util.account_id_from_label(region_util.account_label(row)),
                "demo.user-1")

    def test_id_from_label_placeholders(self):
        self.assertEqual(region_util.account_id_from_label("（无账号）"), "")
        self.assertEqual(region_util.account_id_from_label("全部账号"), "")
        self.assertEqual(region_util.account_id_from_label(""), "")
        self.assertEqual(region_util.account_id_from_label("@plain"), "plain")
        self.assertEqual(region_util.account_id_from_label("plain"), "plain")

    def test_options_include_custom_regions(self):
        opts = region_util.region_options(["越南", "巴西"])
        self.assertIn("越南", opts)
        self.assertIn("缅甸", opts)
        self.assertIn("巴西", opts, "自定义地区应自动进入选项")
        self.assertEqual(len(opts), len(set(opts)), "选项不得重复")

    def test_label_tolerates_sqlite_row_like(self):
        class Row:
            def __getitem__(self, k):
                if k == "username":
                    return "u9"
                if k == "region":
                    return "泰国"
                raise KeyError(k)
        self.assertEqual(region_util.account_label(Row()), "泰国 · @u9")


class TestDisplayName(unittest.TestCase):
    """昵称（display_name）：TikTok 显示名，用于账号页辨识账号。

    关键约束：必须是**单列更新**，不得影响 region 等其它字段。
    """

    def setUp(self):
        self.db = Database(_tmp_db_path("nick.db"))
        self.svc = AccountService(self.db)

    def tearDown(self):
        self.db.close()

    def test_set_display_name_single_column(self):
        self.svc.add("n1", region="越南")
        self.assertTrue(self.db.set_account_display_name("n1", "小美"))
        row = self.db.get_account("n1")
        self.assertEqual(row["display_name"], "小美")
        self.assertEqual(row["region"], "越南", "单列更新不得影响 region")

    def test_no_write_when_value_unchanged(self):
        self.svc.add("n2")
        self.assertTrue(self.db.set_account_display_name("n2", "AAA"))
        self.assertFalse(self.db.set_account_display_name("n2", "AAA"),
                         "值未变化时不应写库")
        self.assertFalse(self.db.set_account_display_name("n2", "   "),
                         "空白昵称应被忽略")

    def test_unknown_account_returns_false(self):
        self.assertFalse(self.db.set_account_display_name("not_exist", "X"))

    def test_display_name_survives_region_change(self):
        self.svc.add("n3", region="越南")
        self.db.set_account_display_name("n3", "昵称A")
        self.svc.set_regions(["n3"], "缅甸")
        row = self.db.get_account("n3")
        self.assertEqual(row["display_name"], "昵称A")
        self.assertEqual(row["region"], "缅甸")

    def test_display_name_survives_collect_count_edit(self):
        """★ 回归：改采集数量不得清空昵称（update 是整行覆盖式 UPDATE）。"""
        self.svc.add("n4")
        self.db.set_account_display_name("n4", "昵称B")
        self.svc.update("n4", collect_count=9)
        row = self.db.get_account("n4")
        self.assertEqual(row["display_name"], "昵称B")
        self.assertEqual(row["collect_count"], 9)


class TestAccountRegionService(unittest.TestCase):
    def setUp(self):
        self.db = Database(_tmp_db_path("svc.db"))
        self.svc = AccountService(self.db)

    def tearDown(self):
        self.db.close()

    def _region(self, username):
        return self.db.get_account(username)["region"]

    def test_add_with_region(self):
        ok, msg = self.svc.add("alpha_one", region="越南")
        self.assertTrue(ok)
        self.assertIn("越南", msg)
        self.assertEqual(self._region("alpha_one"), "越南")

    def test_add_without_region(self):
        self.svc.add("alpha_two")
        self.assertEqual(self._region("alpha_two"), "")

    def test_import_many_with_region(self):
        res = self.svc.import_many(["b_one", "b_two", "@b_three"], region="缅甸")
        self.assertEqual(len(res["imported"]), 3)
        for u in ("b_one", "b_two", "b_three"):
            self.assertEqual(self._region(u), "缅甸")

    def test_set_regions_bulk_then_clear(self):
        self.svc.import_many(["c_one", "c_two"])
        self.assertEqual(self.svc.set_regions(["c_one", "c_two"], "泰国"), 2)
        self.assertEqual(self._region("c_one"), "泰国")
        self.svc.set_regions(["c_one"], "")
        self.assertEqual(self._region("c_one"), "", "空地区表示取消分类")
        self.assertEqual(self._region("c_two"), "泰国")

    def test_set_regions_empty_ids(self):
        self.assertEqual(self.svc.set_regions([], "越南"), 0)

    def test_update_region_explicit(self):
        self.svc.add("g_one", region="越南")
        self.svc.update("g_one", region="缅甸")
        self.assertEqual(self._region("g_one"), "缅甸")

    def test_region_stats(self):
        self.svc.import_many(["d_one", "d_two", "d_three"], region="越南")
        self.svc.import_many(["d_four"], region="缅甸")
        self.svc.import_many(["d_five"])
        stats = dict(self.svc.region_stats())
        self.assertEqual(stats["越南"], 3)
        self.assertEqual(stats["缅甸"], 1)
        self.assertEqual(stats["未分类"], 1)

    def test_region_options_after_custom_add(self):
        self.svc.import_many(["e_one"], region="巴西")
        self.assertIn("巴西", self.svc.region_options())
        self.assertIn("越南", self.svc.region_options())

    def test_list_accounts_filter_by_region(self):
        self.svc.import_many(["f_one", "f_two"], region="越南")
        self.svc.import_many(["f_three"], region="缅甸")
        self.svc.import_many(["f_four"])
        self.assertEqual(len(self.db.list_accounts(region="越南")), 2)
        self.assertEqual(len(self.db.list_accounts(region="缅甸")), 1)
        self.assertEqual(len(self.db.list_accounts(region="")), 1, "空串 = 只看未分类")
        self.assertEqual(len(self.db.list_accounts()), 4, "不传 region = 不筛选")

    def test_filter_combines_with_enabled(self):
        self.svc.import_many(["h_one", "h_two"], region="越南")
        self.svc.set_enabled("h_one", False)
        self.assertEqual(len(self.db.list_accounts(enabled_only=True, region="越南")), 1)
