"""日志系统（P22）：logging 配置 + 按日滚动文件 + 控制台。

- 日志文件按日滚动，保存在 log_dir（默认 logs/）。
- 采集引擎、账号管理、服务层统一通过 get_logger() 获取 logger。
- 单例初始化，重复调用幂等。
"""
from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

_configured = False
_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(log_dir: Optional[str] = None,
                  level: str = "INFO",
                  console: bool = True,
                  keep_days: int = 30) -> None:
    """初始化日志系统（幂等）。

    - 日志文件按日滚动，保留最近 keep_days 天（自动清理旧日志，避免无限增长）。
    """
    global _configured
    if _configured:
        return

    log_dir = log_dir or "logs"
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(_normalize_level(level))

    fmt = logging.Formatter(_DEFAULT_FORMAT)

    # 文件 handler：按日滚动，保留 keep_days 天
    file_path = os.path.join(log_dir, "app.log")
    fh = TimedRotatingFileHandler(
        file_path, when="midnight", interval=1, backupCount=keep_days, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(root.level)
    root.addHandler(fh)

    # 控制台 handler
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        ch.setLevel(root.level)
        root.addHandler(ch)

    _configured = True


def get_logger(name: str = "tiktok_link_collector") -> logging.Logger:
    """获取命名 logger；未初始化时用默认配置兜底。"""
    if not _configured:
        setup_logging()
    return logging.getLogger(name)


def _normalize_level(level: str) -> int:
    return getattr(logging, str(level).upper(), logging.INFO)
