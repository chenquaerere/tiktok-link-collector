"""配置管理：默认值 + JSON 持久化（后续与 settings 表双向同步）。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from .constants import (
    DEFAULT_ACCOUNT_INTERVAL_SECONDS,
    DEFAULT_COLLECT_COUNT,
    DEFAULT_DB_PATH,
    DEFAULT_ERROR_WAIT_MS,
    DEFAULT_EXPORT_DIR,
    DEFAULT_LINKS_LOG_DIR,
    DEFAULT_LOG_DIR,
    DEFAULT_MAX_RETRY,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    DEFAULT_TASK_INTERVAL_MS,
    DEFAULT_TIMEZONE,
)

DEFAULTS: Dict[str, Any] = {
    # 基础
    "default_collect_count": DEFAULT_COLLECT_COUNT,
    "default_date": "today",  # today / yesterday / YYYY-MM-DD
    "timezone": DEFAULT_TIMEZONE,
    "theme": "dark",
    "auto_open_browser_on_start": False,
    # 浏览器
    "browser_type": "chromium",  # chromium / chrome / msedge
    "browser_headless": True,  # 后台采集（无窗口不打扰操作）；需手动登录时临时关掉
    "page_load_timeout_ms": DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    "max_retry": DEFAULT_MAX_RETRY,
    "task_interval_ms": DEFAULT_TASK_INTERVAL_MS,
    "error_wait_ms": DEFAULT_ERROR_WAIT_MS,
    "account_interval_seconds": DEFAULT_ACCOUNT_INTERVAL_SECONDS,
    # 数据
    "db_path": DEFAULT_DB_PATH,
    "export_dir": DEFAULT_EXPORT_DIR,
    "links_log_dir": DEFAULT_LINKS_LOG_DIR,
    "auto_save": True,
    "history_keep_days": 90,
    "notify_sound": True,   # 采集完成/失败声音提示
    # 日志
    "log_level": "INFO",
    "log_dir": DEFAULT_LOG_DIR,
    "log_keep_days": 30,
    # 更新（GitHub Releases：填 owner/repo 即启用自动检查）
    "update_repo": "",       # 如 "yourname/tiktok-link-collector"
    "update_url": "",        # 自定义更新源 JSON（可选，优先级高于 update_repo）
    "auto_check_update": True,  # 启动时静默检查更新
    # 代理（默认关闭，用户自备网络环境）
    "proxy_enabled": False,
    "proxy_type": "http",  # http / https / socks5
    "proxy_host": "",
    "proxy_port": "",
}


class Config:
    def __init__(self, path: str | None = None):
        self.path = path
        self._data: Dict[str, Any] = dict(DEFAULTS)
        if path and os.path.exists(path):
            self.load(path)

    def load(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._data.update(data)
        except (OSError, json.JSONDecodeError):
            # 损坏配置静默回退默认值，不阻断启动
            pass

    def save(self, path: str | None = None) -> None:
        target = path or self.path
        if not target:
            return
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)

    def proxy_config(self) -> Dict[str, Any] | None:
        """返回 Playwright 格式的代理配置；未启用/未配置返回 None。

        代理由用户配置（proxy_enabled/proxy_type/proxy_host/proxy_port），
        本方法不硬编码任何地址。
        """
        if not self.get("proxy_enabled"):
            return None
        host = str(self.get("proxy_host") or "").strip()
        port = str(self.get("proxy_port") or "").strip()
        if not host or not port:
            return None
        ptype = str(self.get("proxy_type") or "http").strip().lower()
        return {"server": f"{ptype}://{host}:{port}"}
