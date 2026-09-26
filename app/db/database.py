"""SQLite 数据访问层：6 张表 + 外键 + 关键索引 + WAL + 事务 + settings + DAO。

设计要点：
- 外键保证 accounts → videos → collect_tasks → task_accounts 的引用完整性。
- 删除账号级联删除其作品/日志；删除任务保留作品（first_task_id 置 NULL）。
- videos.UNIQUE(video_id)：同一作品全局仅一份，首次采集时间记 first_collect_time，
  后续任务再次发现通过 collect_logs(video_id) 记录，不重复创建 video。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator, List, Optional

from app.core.models import Account, Video

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
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

CREATE TABLE IF NOT EXISTS collect_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    target_date TEXT,
    created_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    account_count INTEGER NOT NULL DEFAULT 0,
    target_total INTEGER NOT NULL DEFAULT 0,
    actual_total INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL,
    username TEXT NOT NULL,
    video_url TEXT NOT NULL,
    publish_time TEXT,
    publish_date TEXT,
    first_collect_time TEXT NOT NULL DEFAULT '',
    first_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
    FOREIGN KEY(first_task_id) REFERENCES collect_tasks(task_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS task_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    target_count INTEGER NOT NULL DEFAULT 0,
    actual_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error_reason TEXT NOT NULL DEFAULT '',
    UNIQUE(task_id, account_id),
    FOREIGN KEY(task_id) REFERENCES collect_tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS collect_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    account_id TEXT,
    video_id TEXT,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT,
    created_at TEXT,
    FOREIGN KEY(task_id) REFERENCES collect_tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 聊天链接采集模块（独立板块；SCHEMA_VERSION 不升级，靠 IF NOT EXISTS 幂等追加，
-- 不触碰既有 accounts/videos 等表数据）
CREATE TABLE IF NOT EXISTS chat_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_key TEXT NOT NULL UNIQUE,          -- conv:xxx / secuid:xxx / uid:xxx
    chat_type TEXT NOT NULL,                  -- friend / group
    name TEXT NOT NULL DEFAULT '',
    handle TEXT NOT NULL DEFAULT '',
    uid TEXT NOT NULL DEFAULT '',
    sec_uid TEXT NOT NULL DEFAULT '',
    conversation_id TEXT NOT NULL DEFAULT '',
    last_used_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chat_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_key TEXT NOT NULL,                 -- 所属聊天目标（chat_targets.stable_key）
    video_id TEXT NOT NULL,
    video_url TEXT NOT NULL,
    order_num INTEGER NOT NULL DEFAULT 0,     -- 0 = 最新
    collected_at TEXT NOT NULL DEFAULT '',
    UNIQUE(stable_key, video_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_links_target ON chat_links(stable_key);
CREATE INDEX IF NOT EXISTS idx_chat_targets_used ON chat_targets(last_used_at);

CREATE INDEX IF NOT EXISTS idx_videos_account ON videos(account_id);
CREATE INDEX IF NOT EXISTS idx_videos_publish_date ON videos(publish_date);
CREATE INDEX IF NOT EXISTS idx_videos_first_task ON videos(first_task_id);
CREATE INDEX IF NOT EXISTS idx_task_accounts_task ON task_accounts(task_id);
CREATE INDEX IF NOT EXISTS idx_collect_logs_task ON collect_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_collect_logs_video ON collect_logs(video_id);
"""

# 删除顺序：先子表后父表，避免外键约束报错
_DROP_ALL = """
DROP TABLE IF EXISTS chat_links;
DROP TABLE IF EXISTS chat_targets;
DROP TABLE IF EXISTS collect_logs;
DROP TABLE IF EXISTS task_accounts;
DROP TABLE IF EXISTS videos;
DROP TABLE IF EXISTS collect_tasks;
DROP TABLE IF EXISTS accounts;
DROP TABLE IF EXISTS settings;
"""


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._in_transaction = False
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    # ---- 迁移 ----
    def _migrate(self) -> None:
        with self._lock:
            ver = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if ver != SCHEMA_VERSION:
                # 结构变更：重建业务表（开发阶段无真实数据时可安全重建）
                self.conn.execute("PRAGMA foreign_keys = OFF")
                self.conn.executescript(_DROP_ALL)
                self.conn.executescript(SCHEMA)
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self.conn.execute("PRAGMA foreign_keys = ON")
            else:
                self.conn.executescript(SCHEMA)  # 幂等
            self.conn.commit()

    # ---- 底层执行 ----
    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def _maybe_commit(self) -> None:
        if not self._in_transaction:
            self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._execute(sql, params)
            self._maybe_commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._execute(sql, params).fetchone()

    @contextmanager
    def transaction(self) -> Iterator["Database"]:
        """多步写入事务：异常自动回滚。"""
        with self._lock:
            self._in_transaction = True
            try:
                self._execute("BEGIN")
                yield self
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            finally:
                self._in_transaction = False

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ---- 备份 / 恢复 ----
    def backup(self, target_path: str) -> None:
        """用 SQLite 在线备份 API 生成一致性快照（WAL 模式下也安全，
        自动处理 checkpoint，无需先停写）。"""
        with self._lock:
            dest = sqlite3.connect(target_path)
            try:
                self.conn.backup(dest)
            finally:
                dest.close()

    def restore(self, source_path: str) -> None:
        """从备份文件恢复到当前库（反向 backup，服务层持有的连接无需重建）。"""
        with self._lock:
            src = sqlite3.connect(source_path)
            try:
                src.backup(self.conn)
            finally:
                src.close()

    # ---- settings ----
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    # ---- accounts ----
    def insert_account(self, account: Account, now: Optional[str] = None) -> bool:
        """新增账号，account_id/username/profile_url 任一已存在则忽略。返回是否真正插入。"""
        with self._lock:
            cur = self._execute(
                "INSERT OR IGNORE INTO accounts(account_id, username, profile_url, display_name, "
                "remark, enabled, login_status, collect_count, created_at, updated_at, "
                "last_collect_time, last_collect_result) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (account.account_id, account.username, account.profile_url, account.display_name,
                 account.remark, 1 if account.enabled else 0, account.login_status,
                 account.collect_count, account.created_at or (now or _now_str()),
                 account.updated_at or (now or _now_str()),
                 account.last_collect_time, account.last_collect_result),
            )
            self._maybe_commit()
            return cur.rowcount > 0

    def get_account(self, account_id: str) -> Optional[sqlite3.Row]:
        return self.query_one("SELECT * FROM accounts WHERE account_id = ?", (account_id,))

    def update_account(self, account: Account) -> bool:
        """更新账号（按 account_id）。返回是否有行受影响。"""
        with self._lock:
            cur = self._execute(
                "UPDATE accounts SET display_name=?, remark=?, enabled=?, login_status=?, "
                "collect_count=?, updated_at=? WHERE account_id=?",
                (account.display_name, account.remark, 1 if account.enabled else 0,
                 account.login_status, account.collect_count, _now_str(), account.account_id),
            )
            self._maybe_commit()
            return cur.rowcount > 0

    def set_account_enabled(self, account_id: str, enabled: bool) -> bool:
        with self._lock:
            cur = self._execute(
                "UPDATE accounts SET enabled=?, updated_at=? WHERE account_id=?",
                (1 if enabled else 0, _now_str(), account_id),
            )
            self._maybe_commit()
            return cur.rowcount > 0

    def delete_account(self, account_id: str) -> bool:
        """删除账号（级联删除其 videos/task_accounts/collect_logs）。"""
        with self._lock:
            cur = self._execute("DELETE FROM accounts WHERE account_id=?", (account_id,))
            self._maybe_commit()
            return cur.rowcount > 0

    def set_account_last_collect(self, account_id: str, result: str = "") -> None:
        """更新账号最后采集时间与结果摘要。"""
        with self._lock:
            self._execute(
                "UPDATE accounts SET last_collect_time=?, last_collect_result=? WHERE account_id=?",
                (_now_str(), result, account_id),
            )
            self._maybe_commit()

    def list_accounts(self, enabled_only: bool = False) -> List[sqlite3.Row]:
        if enabled_only:
            return self.query("SELECT * FROM accounts WHERE enabled = 1 ORDER BY id")
        return self.query("SELECT * FROM accounts ORDER BY id")

    def count_accounts(self) -> int:
        row = self.query_one("SELECT COUNT(*) AS c FROM accounts")
        return row["c"] if row else 0

    # ---- collect_tasks ----
    def insert_task(self, task_id: str, target_date: Optional[str] = None,
                    created_at: Optional[str] = None, status: str = "pending") -> bool:
        with self._lock:
            cur = self._execute(
                "INSERT OR IGNORE INTO collect_tasks(task_id, target_date, created_at, status) "
                "VALUES(?,?,?,?)",
                (task_id, target_date, created_at or _now_str(), status),
            )
            self._maybe_commit()
            return cur.rowcount > 0

    def update_task(self, task_id: str, *, status: Optional[str] = None,
                    account_count: Optional[int] = None, target_total: Optional[int] = None,
                    actual_total: Optional[int] = None, success_count: Optional[int] = None,
                    fail_count: Optional[int] = None, completed_at: Optional[str] = None) -> None:
        """更新任务汇总字段（只更新非 None 字段）。"""
        sets, params = [], []
        for col, val in (
            ("status", status), ("account_count", account_count), ("target_total", target_total),
            ("actual_total", actual_total), ("success_count", success_count),
            ("fail_count", fail_count), ("completed_at", completed_at),
        ):
            if val is not None:
                sets.append(f"{col} = ?")
                params.append(val)
        if not sets:
            return
        params.append(task_id)
        with self._lock:
            self._execute(f"UPDATE collect_tasks SET {', '.join(sets)} WHERE task_id = ?", tuple(params))
            self._maybe_commit()

    def next_task_id(self, target_date: str) -> str:
        """生成 TASK-YYYYMMDD-NNN（当日序号递增）。"""
        prefix = "TASK-" + target_date.replace("-", "")
        row = self.query_one(
            "SELECT COUNT(*) AS c FROM collect_tasks WHERE task_id LIKE ?",
            (prefix + "-%",),
        )
        seq = (row["c"] if row else 0) + 1
        return f"{prefix}-{seq:03d}"

    # ---- task_accounts ----
    def upsert_task_account(self, task_id: str, account_id: str, username: str,
                            target_count: int, actual_count: int, status: str,
                            error_reason: str = "") -> None:
        with self._lock:
            self._execute(
                "INSERT INTO task_accounts(task_id, account_id, username, target_count, "
                "actual_count, status, error_reason) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(task_id, account_id) DO UPDATE SET "
                "username=excluded.username, target_count=excluded.target_count, "
                "actual_count=excluded.actual_count, status=excluded.status, "
                "error_reason=excluded.error_reason",
                (task_id, account_id, username, target_count, actual_count, status, error_reason),
            )
            self._maybe_commit()

    # ---- videos ----
    def insert_video(self, video: Video, now: Optional[str] = None) -> bool:
        """首次入库：video_id 已存在则忽略，绝不重复创建。返回是否真正插入。"""
        first_collect_time = video.first_collect_time or now or _now_str()
        with self._lock:
            cur = self._execute(
                "INSERT OR IGNORE INTO videos(video_id, account_id, username, video_url, "
                "publish_time, publish_date, first_collect_time, first_task_id, status) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (video.video_id, video.account_id, video.username, video.video_url,
                 video.publish_time, video.publish_date, first_collect_time,
                 video.first_task_id or None, video.status),
            )
            self._maybe_commit()
            return cur.rowcount > 0

    def video_exists(self, video_id: str) -> bool:
        row = self.query_one("SELECT 1 FROM videos WHERE video_id = ?", (video_id,))
        return row is not None

    def delete_videos_for_account(self, account_id: str) -> int:
        """删除某账号的全部作品记录（替换式记录：新任务前清旧账）。

        返回删除条数。无其他表引用 videos，可安全删除。
        """
        with self._lock:
            cur = self._execute("DELETE FROM videos WHERE account_id = ?", (account_id,))
            self._maybe_commit()
            return cur.rowcount

    def load_all_video_ids(self) -> List[str]:
        """供任务开始前初始化去重器（每日重复执行 + 增量去重）。"""
        return [r["video_id"] for r in self.query("SELECT video_id FROM videos")]

    def count_videos(self) -> int:
        row = self.query_one("SELECT COUNT(*) AS c FROM videos")
        return row["c"] if row else 0

    # ---- 作品查询（结果页 / 历史 / 导出） ----
    def query_videos(self, *, account_id: Optional[str] = None,
                     publish_date: Optional[str] = None,
                     task_id: Optional[str] = None) -> List[sqlite3.Row]:
        """按账号 / 发布日期 / 任务 组合查询作品（按发布时间倒序）。"""
        sql = "SELECT * FROM videos WHERE 1=1"
        params: list = []
        if account_id is not None:
            sql += " AND account_id = ?"
            params.append(account_id)
        if publish_date is not None:
            sql += " AND publish_date = ?"
            params.append(publish_date)
        if task_id is not None:
            sql += " AND first_task_id = ?"
            params.append(task_id)
        sql += " ORDER BY publish_time DESC"
        return self.query(sql, tuple(params))

    def delete_videos(self, *, account_id: Optional[str] = None,
                      publish_date: Optional[str] = None) -> int:
        """按账号 / 发布日期删除作品记录（清空用），返回删除条数。

        与 query_videos 同一套过滤条件；都不传 = 清空全部。
        """
        sql = "DELETE FROM videos WHERE 1=1"
        params: list = []
        if account_id is not None:
            sql += " AND account_id = ?"
            params.append(account_id)
        if publish_date is not None:
            sql += " AND publish_date = ?"
            params.append(publish_date)
        with self.transaction():
            cur = self.execute(sql, tuple(params))
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def list_tasks(self, limit: int = 50) -> List[sqlite3.Row]:
        return self.query(
            "SELECT * FROM collect_tasks ORDER BY created_at DESC LIMIT ?", (limit,))

    def get_task(self, task_id: str) -> Optional[sqlite3.Row]:
        return self.query_one("SELECT * FROM collect_tasks WHERE task_id = ?", (task_id,))

    def list_task_accounts(self, task_id: str) -> List[sqlite3.Row]:
        return self.query(
            "SELECT * FROM task_accounts WHERE task_id = ? ORDER BY id", (task_id,))

    # ---- 任务恢复（断点续传） ----
    def find_unfinished_task(self) -> Optional[sqlite3.Row]:
        """返回最近一个未完成任务（running/stopped/pending），用于重启后恢复。"""
        return self.query_one(
            "SELECT * FROM collect_tasks WHERE status IN ('running','stopped','pending') "
            "ORDER BY created_at DESC LIMIT 1")

    def unfinished_account_ids(self, task_id: str) -> List[str]:
        """返回某任务尚未完成的账号 id（failed/skipped/pending/running）。

        已完成（completed/partial/empty）的账号不在续跑范围，
        但注意：partial/empty 表示「当日已查清，无需再采」，故视为完成。
        """
        rows = self.query(
            "SELECT account_id FROM task_accounts WHERE task_id = ? AND status NOT IN "
            "('completed', 'partial', 'empty')",
            (task_id,),
        )
        return [r["account_id"] for r in rows]

    # ---- collect_logs ----
    def insert_collect_log(self, task_id: Optional[str], account_id: Optional[str],
                           message: str, level: str = "info",
                           video_id: Optional[str] = None, now: Optional[str] = None) -> None:
        with self._lock:
            self._execute(
                "INSERT INTO collect_logs(task_id, account_id, video_id, level, message, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (task_id, account_id, video_id, level, message, now or _now_str()),
            )
            self._maybe_commit()

    # ---- 诊断 ----
    def table_names(self) -> List[str]:
        rows = self.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [r["name"] for r in rows]

    def index_names(self) -> List[str]:
        rows = self.query("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")
        return [r["name"] for r in rows]

    def journal_mode(self) -> str:
        row = self.query_one("PRAGMA journal_mode")
        return row[0] if row else ""

    def foreign_keys_enabled(self) -> bool:
        row = self.query_one("PRAGMA foreign_keys")
        return bool(row[0]) if row else False
