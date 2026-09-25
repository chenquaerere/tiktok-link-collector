"""页面基类：统一背景色，提供 refresh/on_leave 生命周期钩子 + 交互便捷方法。"""
from __future__ import annotations

import customtkinter as ctk

from ..theme import COLORS


class BasePage(ctk.CTkFrame):
    """所有页面的基类：统一背景色，提供 refresh/on_leave 生命周期钩子。"""

    def __init__(self, master, ctx, **kw):
        super().__init__(master, fg_color=COLORS["bg"], corner_radius=0, **kw)
        self.ctx = ctx
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

    # ---- 生命周期 ----
    def refresh(self) -> None:
        """切换到本页时刷新数据（子类覆盖）。"""

    def on_leave(self) -> None:
        """离开本页时的清理（子类覆盖）。"""

    # ---- 交互便捷方法 ----
    @property
    def window(self):
        """主窗口（AppWindow），提供 toast/confirm 等能力。"""
        return getattr(self.ctx, "window", None) or self.winfo_toplevel()

    def toast(self, message: str, title: str = "", level: str = "info",
              duration: int = 3200) -> None:
        """全局 Toast（非阻塞）。level: info/success/warning/error。"""
        win = self.window
        mgr = getattr(win, "toast", None)
        if mgr is not None:
            mgr.show(message, title=title, level=level, duration=duration)
        else:
            from .widgets import show_info
            show_info(self, title, message)

    def confirm(self, title: str, message: str, danger: bool = False) -> bool:
        """样式化确认弹窗。"""
        from .components.dialog import confirm as _confirm
        return _confirm(self, title, message, danger=danger)

    def show_error_dialog(self, title: str, message: str, suggestion: str = "") -> None:
        """样式化错误弹窗（标题 + 原因 + 建议）。"""
        from .components.dialog import error as _error
        _error(self, title, message, suggestion)

    def set_status(self, text: str) -> None:
        """更新底部状态栏文案。"""
        win = self.window
        if hasattr(win, "set_status"):
            win.set_status(text)
