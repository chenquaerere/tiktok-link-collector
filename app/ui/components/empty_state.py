"""空状态组件：数据为空时的友好引导，避免空白区域。"""
from __future__ import annotations

import customtkinter as ctk
from typing import Optional, Callable

from ..theme import COLORS, FONT, SPACING

_GLYPHS = {
    "account": "👤", "link": "🔗", "task": "📋", "history": "🕘",
    "log": "📄", "result": "📦", "setting": "⚙️", "dashboard": "📊",
    "default": "🗂",
}


class EmptyState(ctk.CTkFrame):
    """居中展示图标 + 标题 + 副标题 + 可选动作按钮。"""

    def __init__(self, master, title: str = "暂无数据", subtitle: str = "",
                 icon: str = "default", action_text: str = "",
                 action_command: Optional[Callable[[], None]] = None, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure((0, 1, 2, 3), weight=0)
        self.grid_rowconfigure(4, weight=1)

        glyph = _GLYPHS.get(icon, _GLYPHS["default"])
        ctk.CTkLabel(self, text=glyph, font=(FONT["app_title"][0], 40),
                     text_color=COLORS["text_faint"]).grid(
            row=0, column=0, pady=(28, 6))
        ctk.CTkLabel(self, text=title, font=FONT["body_strong"],
                     text_color=COLORS["text_dim"]).grid(row=1, column=0, pady=2)
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=FONT["secondary"],
                         text_color=COLORS["text_faint"], justify="center").grid(
                row=2, column=0, pady=(2, 6))
        if action_text and action_command:
            ctk.CTkButton(self, text=action_text, width=140, height=36,
                          font=FONT["button"], fg_color=COLORS["primary"],
                          hover_color=COLORS["primary_hover"],
                          command=action_command).grid(row=3, column=0, pady=(8, 4))
        # 底部留白，保证在 grid 容器里也能上下居中
        ctk.CTkFrame(self, fg_color="transparent", height=20).grid(
            row=4, column=0, pady=(0, 20))
