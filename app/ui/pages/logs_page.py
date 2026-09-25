"""日志页面：查看应用日志文件（后台读取 + 级别着色 + 级别筛选）。"""
from __future__ import annotations

import os
import threading

import customtkinter as ctk

from app.app import resolve_path

from ..theme import COLORS, FONT
from ..components import EmptyState, PageHeader
from .base_page import BasePage

_LEVEL_COLOR = {
    "ERROR": COLORS["danger"],
    "CRITICAL": COLORS["danger"],
    "WARNING": COLORS["warning"],
    "WARN": COLORS["warning"],
    "DEBUG": COLORS["text_faint"],
    "INFO": COLORS["text_dim"],
}


class LogsPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._lines = []
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "日志", "应用运行日志（最近 500 行）")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 8))
        self.header.add_action("打开日志目录", self._open_dir, kind="ghost", width=120)
        self.header.add_action("刷新", self._load, kind="primary", width=80)

        # 级别筛选
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 6))
        ctk.CTkLabel(bar, text="级别筛选", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).pack(side="left")
        self._level_filter = ctk.CTkComboBox(
            bar, values=["全部", "INFO", "DEBUG", "WARNING", "ERROR"],
            width=120, font=FONT["body"], command=lambda _: self._render())
        self._level_filter.set("全部")
        self._level_filter.pack(side="left", padx=8)
        self._path_lbl = ctk.CTkLabel(bar, text="", font=FONT["caption"],
                                      text_color=COLORS["text_faint"], anchor="e")
        self._path_lbl.pack(side="right")

        self._text = ctk.CTkTextbox(self, font=FONT["mono"], fg_color=COLORS["surface"],
                                    text_color=COLORS["text"], wrap="none")
        self._text.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 20))
        self._text.configure(state="disabled")
        self.grid_rowconfigure(2, weight=1)
        for tag, color in _LEVEL_COLOR.items():
            self._text.tag_config(tag, foreground=color)

        self._empty = EmptyState(
            self, title="暂无日志", subtitle="开始采集后，运行日志会显示在这里",
            icon="log")
        self._empty.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 20))
        self._empty.grid_remove()

    def _log_path(self) -> str:
        log_dir = resolve_path(self.ctx.base_dir, self.ctx.config.get("log_dir"))
        return os.path.join(log_dir, "app.log")

    def refresh(self) -> None:
        self._load()

    def _load(self) -> None:
        path = self._log_path()
        self._path_lbl.configure(text=path)
        self.set_status("读取日志…")

        def worker():
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                tail = lines[-500:]
            except FileNotFoundError:
                tail = None
            except Exception as exc:  # noqa: BLE001
                tail = [f"读取失败：{exc}\n"]
            self.after(0, lambda: self._on_loaded(tail))

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, lines) -> None:
        self.set_status("就绪")
        self._lines = lines if lines is not None else []
        self._render()

    def _level_of(self, line: str) -> str:
        up = line.upper()
        for lv in ("CRITICAL", "ERROR", "WARNING", "WARN", "DEBUG", "INFO"):
            if lv in up:
                return "WARNING" if lv == "WARN" else lv
        return ""

    def _render(self) -> None:
        f = self._level_filter.get()
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        if not self._lines:
            self._text.configure(state="disabled")
            self._text.grid_remove()
            self._empty.grid()
            return
        self._empty.grid_remove()
        self._text.grid()

        shown = 0
        for line in self._lines:
            lv = self._level_of(line)
            if f != "全部" and lv != f:
                continue
            start = self._text.index("end-1c")
            self._text.insert("end", line)
            end = self._text.index("end-1c")
            if lv in _LEVEL_COLOR:
                self._text.tag_add(lv, start, end)
            shown += 1
        self._text.configure(state="disabled")
        self._text.see("end")

    def _open_dir(self) -> None:
        path = self._log_path()
        d = os.path.dirname(path)
        try:
            os.startfile(d)  # noqa: Windows 专用
        except Exception:
            self.toast(f"日志目录：\n{d}", title="日志目录", level="info", duration=5000)
