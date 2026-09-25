"""状态徽章组件：彩色圆点 + 文案的小胶囊，用于卡片/横幅等非表格场景。"""
from __future__ import annotations

import customtkinter as ctk

from ..theme import COLORS, FONT, RADIUS
from ..widgets import status_color, status_zh


class StatusBadge(ctk.CTkFrame):
    """状态徽章：圆点 + 中文状态文案。"""

    def __init__(self, master, status: str, **kw):
        self._status = (status or "").lower()
        color = status_color(self._status)
        kw.setdefault("fg_color", COLORS["surface"])
        kw.setdefault("corner_radius", RADIUS["pill"])
        super().__init__(master, **kw)

        dot = ctk.CTkFrame(self, width=8, height=8, corner_radius=4, fg_color=color)
        dot.pack(side="left", padx=(10, 6), pady=6)
        ctk.CTkLabel(self, text=status_zh(self._status), font=FONT["secondary"],
                     text_color=color).pack(side="left", padx=(0, 10), pady=4)

    def set_status(self, status: str) -> None:
        self._status = (status or "").lower()
        color = status_color(self._status)
        # 重建内部控件以刷新颜色
        for w in self.winfo_children():
            w.destroy()
        dot = ctk.CTkFrame(self, width=8, height=8, corner_radius=4, fg_color=color)
        dot.pack(side="left", padx=(10, 6), pady=6)
        ctk.CTkLabel(self, text=status_zh(self._status), font=FONT["secondary"],
                     text_color=color).pack(side="left", padx=(0, 10), pady=4)
