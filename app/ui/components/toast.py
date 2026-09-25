"""全局 Toast 组件：非阻塞轻提示，替代阻塞式 MessageBox。

设计目标：
- 右下角堆叠展示，自动消失，可悬停暂停倒计时。
- 四种级别（info/success/warning/error）对应图标与主题色。
- ToastManager 挂在主窗口（AppWindow）上，页面通过 `self.toast(...)` 调用。
"""
from __future__ import annotations

import customtkinter as ctk
import tkinter as tk

from ..theme import COLORS, FONT, RADIUS

_LEVEL = {
    "info":    ("i", COLORS["info"]),
    "success": ("✓", COLORS["success"]),
    "warning": ("!", COLORS["warning"]),
    "error":   ("✕", COLORS["danger"]),
}

_DEFAULT_DURATION = 3200  # ms


class Toast(ctk.CTkFrame):
    """单条 Toast：图标 + 标题 + 消息 + 关闭按钮。"""

    def __init__(self, master, message: str, title: str = "", level: str = "info",
                 duration: int = _DEFAULT_DURATION, on_close=None):
        icon, color = _LEVEL.get(level, _LEVEL["info"])
        super().__init__(
            master, fg_color=COLORS["surface_alt"], corner_radius=RADIUS["md"],
            border_width=1, border_color=color,
        )
        self.grid_columnconfigure(1, weight=1)

        self._icon = ctk.CTkLabel(
            self, text=icon, font=(FONT["app_title"][0], 15, "bold"),
            text_color=color, width=28, height=28,
            fg_color=COLORS["surface"], corner_radius=14,
        )
        self._icon.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=12)

        row = 0
        if title:
            self._title = ctk.CTkLabel(self, text=title, font=FONT["body_strong"],
                                       text_color=COLORS["text"], anchor="w")
            self._title.grid(row=row, column=1, sticky="w", pady=(12, 0))
            row = 1
        self._msg = ctk.CTkLabel(self, text=message, font=FONT["secondary"],
                                 text_color=COLORS["text_dim"], anchor="w",
                                 wraplength=300, justify="left")
        self._msg.grid(row=row, column=1, sticky="w",
                       pady=(0 if title else 12, 12))

        self._close = ctk.CTkLabel(self, text="✕", font=FONT["secondary"],
                                   text_color=COLORS["text_faint"], width=22, cursor="hand2")
        self._close.grid(row=0, column=2, sticky="ne", padx=(0, 8), pady=6)
        self._close.bind("<Button-1>", lambda _e: self._dismiss())

        self._duration = duration
        self._after_id = None
        self._on_close = on_close
        self._schedule()
        self.bind("<Enter>", lambda _e: self._cancel())
        self.bind("<Leave>", lambda _e: self._schedule())

    def _cancel(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _schedule(self) -> None:
        self._cancel()
        self._after_id = self.after(self._duration, self._dismiss)

    def _dismiss(self) -> None:
        self._cancel()
        if self._on_close:
            self._on_close(self)
        self.destroy()


class ToastManager:
    """挂在主窗口上，右下角堆叠管理 Toast。"""

    def __init__(self, root):
        self.root = root
        self._container = None

    def _ensure(self):
        if self._container is None or not self._container.winfo_exists():
            self._container = ctk.CTkFrame(self.root, fg_color="transparent")
            self._container.place(relx=1.0, rely=1.0, anchor="se", x=-16, y=-16)
        self._container.lift()
        return self._container

    def show(self, message: str, title: str = "", level: str = "info",
             duration: int = _DEFAULT_DURATION) -> Toast:
        container = self._ensure()
        toast = Toast(container, message, title=title, level=level, duration=duration)
        toast.pack(side="bottom", anchor="se", pady=4)
        return toast
