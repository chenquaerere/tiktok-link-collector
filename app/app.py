"""应用装配层：路径解析、配置、数据库、服务、采集引擎的组装。

main.py 只做薄入口，真正装配在这里，便于测试与打包复用。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from app.config import Config
from app.constants import APP_NAME, APP_NAME_CN, APP_VERSION, DEFAULT_TIMEZONE
from app.core.date_resolver import DateResolver
from app.db.database import Database
from app.log.daily_links import DailyLinksLog
from app.log.logger import get_logger, setup_logging
from app.services.account_service import AccountService
from app.services.result_service import ResultService


def app_dir() -> Path:
    """返回应用数据根目录。

    - 源码运行：项目根目录
    - PyInstaller 打包后（frozen）：exe 所在目录
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_path(base: Path, p: str) -> str:
    """把配置里的相对路径解析为绝对路径（相对 app_dir）。"""
    p = str(p or "")
    if not p:
        return str(base)
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    return str(base / pp)


class AppServices:
    """应用依赖容器：所有页面共享的服务入口。"""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or app_dir()
        self.config_path = self.base_dir / "config.json"
        self.config = Config(str(self.config_path))

        # 日志（先于其它模块初始化）
        setup_logging(
            log_dir=resolve_path(self.base_dir, self.config.get("log_dir")),
            level=self.config.get("log_level", "INFO"),
            keep_days=int(self.config.get("log_keep_days", 30)),
        )
        self.logger = get_logger("app")

        # 数据库
        db_path = resolve_path(self.base_dir, self.config.get("db_path"))
        self.db = Database(db_path)

        # 服务层
        self.account_service = AccountService(self.db)
        self.result_service = ResultService(self.db)
        self.daily_links = DailyLinksLog(
            resolve_path(self.base_dir, self.config.get("links_log_dir"))
        )

        # 采集引擎（惰性构建，避免启动即加载 playwright）
        self._engine = None
        self._collector = None

    # ---- 采集引擎 ----
    def timezone(self) -> str:
        tz = str(self.config.get("timezone") or "").strip()
        if not tz or tz.lower() == "auto":
            return DEFAULT_TIMEZONE
        return tz

    def build_collector(self):
        """构建 ProfileCollector（含浏览器/会话/站点/解析器）。"""
        if self._collector is not None:
            return self._collector
        from app.collector.browser import BrowserManager
        from app.collector.profile_collector import ProfileCollector
        from app.collector.provider import TikTokProvider
        from app.collector.session import SessionManager
        from app.collector.video_parser import VideoParser

        browser = BrowserManager(
            headless=bool(self.config.get("browser_headless")),
            proxy=self.config.proxy_config(),
        )
        session = SessionManager(data_dir=resolve_path(self.base_dir, "data"))
        provider = TikTokProvider(
            load_timeout_ms=int(self.config.get("page_load_timeout_ms", 30000))
        )
        parser = VideoParser()
        self._collector = ProfileCollector(browser, session, provider, parser)
        return self._collector

    def build_engine(self):
        """构建 CollectEngine（单例）。"""
        if self._engine is not None:
            return self._engine
        from app.collector.engine import CollectEngine

        resolver = DateResolver(self.timezone())
        collector = self.build_collector()
        self._engine = CollectEngine(
            self.db,
            collector,
            resolver,
            max_retry=int(self.config.get("max_retry", 3)),
            account_interval_seconds=float(self.config.get("account_interval_seconds", 4.0)),
            daily_links=self.daily_links,
            logger=get_logger("collector.engine"),
        )
        return self._engine

    def reset_engine(self) -> None:
        """配置变更后重建引擎（如代理/间隔改动）。"""
        self._engine = None
        self._collector = None

    def save_config(self) -> None:
        self.config.save(str(self.config_path))

    # ---- 更新检查 ----
    def resolve_update_url(self) -> str:
        """解析最终更新源地址。自定义 URL 优先，其次 GitHub 仓库。"""
        custom = str(self.config.get("update_url") or "").strip()
        if custom:
            return custom
        repo = str(self.config.get("update_repo") or "").strip()
        if repo:
            from app.update import github_latest_url
            return github_latest_url(repo)
        return ""

    def check_for_update(self):
        """检查更新。返回 UpdateInfo 或 None（未配置 / 失败 / 已最新）。"""
        from app.update import check_update
        from app.constants import APP_VERSION

        url = self.resolve_update_url()
        if not url:
            return None
        return check_update(url, APP_VERSION)

    # ---- 数据库备份 / 恢复 ----
    def backup_dir(self) -> Path:
        return self.base_dir / "backups"

    def backup_database(self, keep: int = 10) -> Path:
        """备份数据库到 backups/，返回备份文件路径（保留最近 keep 份）。"""
        from datetime import datetime

        d = self.backup_dir()
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = d / f"tiktok_link_collector_{ts}.db"
        self.db.backup(str(target))
        self.logger.info("数据库已备份到 %s", target)
        # 轮转清理旧备份（保留最近 keep 份）；失败静默跳过，不阻断
        try:
            backups = sorted(d.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[keep:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        return target

    def list_backups(self) -> list:
        d = self.backup_dir()
        if not d.exists():
            return []
        return sorted(d.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)

    def restore_database(self, source_path: str) -> bool:
        """从备份恢复到当前库。失败返回 False。"""
        try:
            self.db.restore(source_path)
            self.logger.info("数据库已从 %s 恢复", source_path)
            return True
        except Exception:
            self.logger.exception("数据库恢复失败")
            return False

    def auto_backup(self) -> Optional[Path]:
        """启动时每日自动备份一次（依据 settings.last_backup_date 去重）。"""
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        if self.db.get_setting("last_backup_date") == today:
            return None
        target = self.backup_database()
        self.db.set_setting("last_backup_date", today)
        return target

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass


def run() -> int:
    """应用入口：装配服务 + 启动主窗口。"""
    from app.ui.theme import enable_high_dpi
    enable_high_dpi()

    from app.ui.app_window import AppWindow

    ctx = AppServices()
    # 启动时每日自动备份一次（失败不阻断启动）
    try:
        ctx.auto_backup()
    except Exception:
        pass

    app = AppWindow(ctx)
    app.mainloop()
    ctx.close()
    return 0
