"""设置页面：基础 / 浏览器 / 代理 / 数据 / 日志 / 关于 分组。"""
from __future__ import annotations

import customtkinter as ctk

from app.constants import APP_NAME_CN, APP_VERSION, COMMON_TIMEZONES

from ..theme import COLORS, FONT
from ..components import PageHeader
from .base_page import BasePage


class SettingsPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._vars = {}
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "设置", "采集、浏览器、代理与数据选项")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 12))
        scroll.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        r = 0
        r = self._section(scroll, "基础", r)
        r = self._entry_row(scroll, "默认采集数量", "default_collect_count", r)
        r = self._switch_row(scroll, "采集完成声音提示", "notify_sound", r)
        r = self._combo_row(scroll, "时区", "timezone", COMMON_TIMEZONES, r)

        r = self._section(scroll, "浏览器", r)
        r = self._switch_row(scroll, "后台采集（不弹窗口、不打扰电脑操作，推荐开启）",
                             "browser_headless", r)
        r = self._entry_row(scroll, "页面加载超时(毫秒)", "page_load_timeout_ms", r)
        r = self._entry_row(scroll, "最大重试次数", "max_retry", r)
        r = self._entry_row(scroll, "账号间隔(秒)", "account_interval_seconds", r)

        r = self._section(scroll, "代理（默认关闭，自备网络环境）", r)
        r = self._switch_row(scroll, "启用代理", "proxy_enabled", r)
        r = self._combo_row(scroll, "代理类型", "proxy_type", ["http", "https", "socks5"], r)
        r = self._entry_row(scroll, "代理主机", "proxy_host", r)
        r = self._entry_row(scroll, "代理端口", "proxy_port", r)

        r = self._section(scroll, "数据", r)
        r = self._entry_row(scroll, "导出目录", "export_dir", r)
        r = self._entry_row(scroll, "历史保留(天)", "history_keep_days", r)
        r = self._backup_row(scroll, r)

        r = self._section(scroll, "日志", r)
        r = self._combo_row(scroll, "日志级别", "log_level",
                            ["DEBUG", "INFO", "WARNING", "ERROR"], r)
        r = self._entry_row(scroll, "日志目录", "log_dir", r)
        r = self._entry_row(scroll, "日志保留(天)", "log_keep_days", r)

        r = self._section(scroll, "更新", r)
        r = self._switch_row(scroll, "启动时自动检查更新", "auto_check_update", r)
        r = self._entry_row(scroll, "GitHub 仓库(owner/repo)", "update_repo", r)

        r = self._section(scroll, "关于", r)
        info = ctk.CTkFrame(scroll, fg_color=COLORS["surface"], corner_radius=10)
        info.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        info.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(info, text=f"{APP_NAME_CN}  v{APP_VERSION}", font=FONT["body_strong"],
                     text_color=COLORS["text"], anchor="w").grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(info, text="批量采集本人 TikTok 账号的作品链接，数据本地存储。",
                     font=FONT["secondary"], text_color=COLORS["text_dim"], anchor="w").grid(
            row=1, column=0, sticky="w", padx=14, pady=(0, 12))
        ctk.CTkButton(info, text="检查更新", width=96, height=32,
                      fg_color=COLORS["surface_alt"], command=self._check_update).grid(
            row=0, column=1, rowspan=2, padx=10)
        r += 1

        # 保存按钮
        bar = ctk.CTkFrame(scroll, fg_color="transparent")
        bar.grid(row=r, column=0, sticky="w", pady=14)
        ctk.CTkButton(bar, text="保存设置", width=120, height=38, fg_color=COLORS["primary"],
                      command=self._save).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="恢复默认", width=100, height=38, fg_color=COLORS["surface_alt"],
                      command=self._reset).pack(side="left", padx=4)

    # ---- 构建辅助 ----
    def _section(self, parent, title, row) -> int:
        ctk.CTkLabel(parent, text=title, font=FONT["section"],
                     text_color=COLORS["accent"], anchor="w").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4))
        return row + 1

    def _entry_row(self, parent, label, key, row) -> int:
        ctk.CTkLabel(parent, text=label, font=FONT["secondary"],
                     text_color=COLORS["text_dim"], anchor="w").grid(
            row=row, column=0, sticky="w", padx=4, pady=4)
        entry = ctk.CTkEntry(parent, font=FONT["body"], height=34)
        entry.insert(0, str(self.ctx.config.get(key, "")))
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        parent.grid_columnconfigure(1, weight=1)
        self._vars[key] = entry
        return row + 1

    def _switch_row(self, parent, label, key, row) -> int:
        var = ctk.BooleanVar(value=bool(self.ctx.config.get(key, False)))
        ctk.CTkLabel(parent, text=label, font=FONT["secondary"],
                     text_color=COLORS["text_dim"], anchor="w").grid(
            row=row, column=0, sticky="w", padx=4, pady=6)
        sw = ctk.CTkSwitch(parent, variable=var, text="", width=48)
        sw.grid(row=row, column=1, sticky="w", padx=8, pady=6)
        self._vars[key] = var
        return row + 1

    def _combo_row(self, parent, label, key, values, row) -> int:
        ctk.CTkLabel(parent, text=label, font=FONT["secondary"],
                     text_color=COLORS["text_dim"], anchor="w").grid(
            row=row, column=0, sticky="w", padx=4, pady=4)
        cur = str(self.ctx.config.get(key, ""))
        combo = ctk.CTkComboBox(parent, values=list(values), font=FONT["body"], height=34)
        combo.set(cur if cur in values else (values[0] if values else ""))
        combo.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        self._vars[key] = combo
        return row + 1

    def _backup_row(self, parent, row) -> int:
        """数据库备份/恢复操作行。"""
        box = ctk.CTkFrame(parent, fg_color=COLORS["surface"], corner_radius=10)
        box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text="数据库备份", font=FONT["body_strong"],
                     text_color=COLORS["text"], anchor="w").grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(box, text="启动时每日自动备份一次，保留最近 10 份。",
                     font=FONT["secondary"], text_color=COLORS["text_dim"], anchor="w").grid(
            row=1, column=0, sticky="w", padx=14, pady=(0, 10))
        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.grid(row=0, column=1, rowspan=2, padx=10)
        ctk.CTkButton(btns, text="立即备份", width=96, height=34, fg_color=COLORS["primary"],
                      command=self._backup_now).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="从备份恢复", width=110, height=34, fg_color=COLORS["surface_alt"],
                      command=self._restore_backup).pack(side="left", padx=4)
        return row + 1

    # ---- 动作 ----
    def refresh(self) -> None:
        pass

    def _check_update(self) -> None:
        """检查更新：复用主窗口集中逻辑（后台线程 + 新版弹窗）。"""
        win = getattr(self.ctx, "window", None)
        if win is not None:
            win.check_update(silent=False)
        else:
            self.toast("当前已是最新版本", title="检查更新", level="info")

    def _backup_now(self) -> None:
        try:
            path = self.ctx.backup_database()
            self.toast(f"备份成功：{path.name}", title="备份完成", level="success")
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.exception("手动备份失败")
            self.show_error_dialog("备份失败", str(exc), "建议：确认磁盘可写后重试。")

    def _restore_backup(self) -> None:
        backups = self.ctx.list_backups()
        if not backups:
            self.toast("暂无备份文件", title="提示", level="info")
            return
        latest = backups[0]
        if not self.confirm("恢复数据库",
                            f"将从备份 {latest.name} 恢复，当前数据会被覆盖。\n确定恢复？",
                            danger=True):
            return
        if self.ctx.restore_database(str(latest)):
            self.toast("数据库已恢复，重启后生效", title="恢复完成",
                       level="success", duration=6000)
        else:
            self.show_error_dialog("恢复失败", "从备份恢复数据库失败",
                                   "建议：确认备份文件完整后重试。")

    def _save(self) -> None:
        cfg = self.ctx.config
        int_keys = {"default_collect_count", "page_load_timeout_ms", "max_retry",
                    "history_keep_days", "log_keep_days"}
        float_keys = {"account_interval_seconds"}
        for key, widget in self._vars.items():
            if isinstance(widget, ctk.BooleanVar):
                cfg.set(key, bool(widget.get()))
                continue
            val = widget.get() if hasattr(widget, "get") else ""
            if key in int_keys:
                try:
                    cfg.set(key, int(str(val).strip()))
                except ValueError:
                    continue
            elif key in float_keys:
                try:
                    cfg.set(key, float(str(val).strip()))
                except ValueError:
                    continue
            else:
                cfg.set(key, str(val))
        self.ctx.save_config()
        self.ctx.reset_engine()  # 代理/间隔等改动即时生效
        self.toast("设置已保存并生效", title="已保存", level="success")

    def _reset(self) -> None:
        from app.config import DEFAULTS
        for key in self._vars:
            self.ctx.config.set(key, DEFAULTS.get(key))
        self.ctx.save_config()
        self._vars.clear()
        for w in self.winfo_children():
            w.destroy()
        self._build()
        self.toast("已恢复默认设置", title="已恢复", level="success")
