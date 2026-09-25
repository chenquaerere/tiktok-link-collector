"""加载状态组件：旋转 spinner + 说明文字（用于导出/读日志等后台任务）。"""
from __future__ import annotations

import customtkinter as ctk

from ..theme import COLORS, FONT

_SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class LoadingState(ctk.CTkFrame):
    """水平 spinner + 文字，可嵌入任意容器。"""

    def __init__(self, master, text: str = "处理中…", **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self._frame = 0
        self._after_id = None

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.grid(row=0, column=0, pady=20)
        self._spin = ctk.CTkLabel(inner, text=_SPIN_FRAMES[0],
                                  font=(FONT["app_title"][0], 18, "bold"),
                                  text_color=COLORS["primary"], width=28)
        self._spin.pack(side="left", padx=(0, 8))
        self._label = ctk.CTkLabel(inner, text=text, font=FONT["body"],
                                   text_color=COLORS["text_dim"])
        self._label.pack(side="left")
        self._animate()

    def set_text(self, text: str) -> None:
        self._label.configure(text=text)

    def _animate(self) -> None:
        self._frame = (self._frame + 1) % len(_SPIN_FRAMES)
        try:
            self._spin.configure(text=_SPIN_FRAMES[self._frame])
        except Exception:
            pass
        self._after_id = self.after(80, self._animate)

    def stop(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
