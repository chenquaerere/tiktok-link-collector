"""页面头部组件：标题 + 副标题 + 右侧动作区，统一各页视觉。"""
from __future__ import annotations

import customtkinter as ctk

from ..theme import COLORS, FONT, SPACING


class PageHeader(ctk.CTkFrame):
    """统一页面头：左侧标题/副标题，右侧动作按钮（通过 self.actions 添加）。"""

    def __init__(self, master, title: str, subtitle: str = "", **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(left, text=title, font=FONT["page_title"],
                     text_color=COLORS["text"], anchor="w").pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(left, text=subtitle, font=FONT["secondary"],
                         text_color=COLORS["text_dim"], anchor="w").pack(
                anchor="w", pady=(2, 0))

        self.actions = ctk.CTkFrame(self, fg_color="transparent")
        self.actions.grid(row=0, column=1, sticky="e")

    def add_action(self, text: str, command, *, width: int = 100, height: int = 34,
                   color: str | None = None, hover: str | None = None,
                   kind: str = "primary") -> ctk.CTkButton:
        """便捷添加右侧动作按钮。kind: primary/accent/ghost/danger。"""
        palette = {
            "primary": (COLORS["primary"], COLORS["primary_hover"]),
            "accent": (COLORS["accent"], COLORS["accent_hover"]),
            "ghost": (COLORS["surface_alt"], COLORS["border"]),
            "danger": (COLORS["danger"], COLORS["danger_hover"]),
        }
        fg, hov = palette.get(kind, palette["primary"])
        btn = ctk.CTkButton(self.actions, text=text, width=width, height=height,
                            font=FONT["button"], fg_color=color or fg,
                            hover_color=hover or hov, command=command)
        btn.pack(side="left", padx=(4, 0))
        return btn
