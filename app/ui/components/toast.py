"""全局 Toast 组件：非阻塞轻提示，替代阻塞式 MessageBox。

v2（2026-09-26 彻底重写）：每条 Toast 是一个独立的**无边框置顶浮动窗口**
（tk.Toplevel + overrideredirect），显示在主窗口右下角、状态栏上方。

为什么不再用「主窗口内 place 覆盖层」方案：
- 旧方案把 Toast 放进主窗口里，任何尺寸残留（CTkFrame 默认 200×200、
  modal grab 导致 Leave 事件丢失→倒计时永不触发、销毁后容器不回缩）都会
  在右下角留一块遮住内容面板的黑色底块，且很难根除（已反馈两次）。
- 浮动窗口方案：Toast 销毁 = 窗口销毁，主窗口内**不存在任何占位元素**，
  物理上不可能再出现黑色残块。

设计：
- 四种级别（info/success/warning/error）对应图标与主题色。
- 倒计时自动消失；不做「悬停暂停」（modal grab_set 会让 Leave 事件丢失，
  Toast 永不消失——旧版黑框常驻的另一根因）。
- 多条 Toast 自下而上堆叠。
"""
from __future__ import annotations

import tkinter as tk

from ..theme import COLORS, FONT

_LEVEL = {
    "info":    ("i", COLORS["info"]),
    "success": ("✓", COLORS["success"]),
    "warning": ("!", COLORS["warning"]),
    "error":   ("✕", COLORS["danger"]),
}

_DEFAULT_DURATION = 3200  # ms

_WIDTH = 330        # 固定宽度，视觉稳定
_PAD = 16           # 距主窗口右/下边缘
_STATUS_BAR = 34    # 预留底部状态栏高度
_GAP = 8            # 多条堆叠间距


class Toast(tk.Toplevel):
    """单条 Toast（独立浮动窗口）：图标 + 标题 + 消息 + 关闭按钮。"""

    def __init__(self, root, message: str, title: str = "", level: str = "info",
                 duration: int = _DEFAULT_DURATION, on_close=None,
                 stack_offset: int = 0):
        super().__init__(root)
        self.withdraw()                       # 先隐藏，定位好再显示，避免闪现
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.transient(root)              # 不进任务栏
        except Exception:
            pass

        icon, color = _LEVEL.get(level, _LEVEL["info"])
        self.configure(bg=color)              # 窗口底色 = 级别色，充当 1px 描边

        body = tk.Frame(self, bg=COLORS["surface"])
        body.pack(fill="both", expand=True, padx=1, pady=1)

        # 左侧级别色条
        tk.Frame(body, bg=color, width=4).pack(side="left", fill="y")

        content = tk.Frame(body, bg=COLORS["surface"])
        content.pack(side="left", fill="both", expand=True, padx=(10, 4), pady=10)

        row = tk.Frame(content, bg=COLORS["surface"])
        row.pack(fill="x")
        tk.Label(row, text=icon, font=(FONT["app_title"][0], 12, "bold"),
                 fg=color, bg=COLORS["surface"]).pack(side="left", padx=(0, 8))
        if title:
            tk.Label(row, text=title, font=FONT["body_strong"],
                     fg=COLORS["text"], bg=COLORS["surface"]).pack(side="left")
        close = tk.Label(row, text="✕", font=FONT["caption"],
                         fg=COLORS["text_faint"], bg=COLORS["surface"], cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self.dismiss())

        tk.Label(content, text=message, font=FONT["secondary"], wraplength=_WIDTH - 70,
                 justify="left", anchor="w", fg=COLORS["text_dim"],
                 bg=COLORS["surface"]).pack(fill="x", pady=(2, 0))

        self._duration = max(800, duration)
        self._after_id = None
        self._on_close = on_close

        # ---- 定位：主窗口右下角、状态栏上方，按 stack_offset 向上堆叠 ----
        self.update_idletasks()
        h = max(52, self.winfo_reqheight())
        x = root.winfo_rootx() + root.winfo_width() - _WIDTH - _PAD
        y = (root.winfo_rooty() + root.winfo_height()
             - _STATUS_BAR - _PAD - h - stack_offset)
        self.geometry(f"{_WIDTH}x{h}+{x}+{y}")
        self.deiconify()
        self.lift()

        self._schedule()

    # ---- 倒计时 ----
    def _cancel(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _schedule(self) -> None:
        self._cancel()
        self._after_id = self.after(self._duration, self.dismiss)

    def dismiss(self) -> None:
        self._cancel()
        cb, self._on_close = self._on_close, None
        if cb:
            try:
                cb(self)
            except Exception:
                pass
        self.destroy()


class ToastManager:
    """挂在主窗口上，右下角堆叠管理 Toast（独立浮动窗口方案）。"""

    def __init__(self, root):
        self.root = root
        self._live: list[Toast] = []

    def _stack_offset(self) -> int:
        """已有存活 Toast 的总高度（含间距），新 Toast 叠在其上。"""
        self._live = [t for t in self._live if t.winfo_exists()]
        return sum(t.winfo_height() or 52 for t in self._live) + _GAP * len(self._live)

    def show(self, message: str, title: str = "", level: str = "info",
             duration: int = _DEFAULT_DURATION) -> Toast:
        toast = Toast(self.root, message, title=title, level=level,
                      duration=duration, stack_offset=self._stack_offset(),
                      on_close=self._forget)
        self._live.append(toast)
        return toast

    def _forget(self, toast: Toast) -> None:
        if toast in self._live:
            self._live.remove(toast)
