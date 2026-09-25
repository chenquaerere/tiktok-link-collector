"""UI 通用组件：可滚动表格、统计卡片、状态颜色、弹窗路由。

2026-09-25 产品化升级：
- show_info / show_error 路由到全局 Toast（非阻塞），ask_confirm 路由到样式化对话框。
- ScrollableTable 支持状态行着色（tag_configure）、行点击回调、URL 中间截断。
"""
from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional

from .theme import COLORS, FONT, RADIUS


def status_color(status: str) -> str:
    """状态 -> 颜色（用于徽章/文本着色）。"""
    mapping = {
        "completed": COLORS["success"],
        "partial": COLORS["warning"],
        "empty": COLORS["text_faint"],
        "failed": COLORS["danger"],
        "skipped": COLORS["text_faint"],
        "running": COLORS["info"],
        "pending": COLORS["text_dim"],
        "stopped": COLORS["warning"],
        "ok": COLORS["success"],
        "unknown": COLORS["text_faint"],
        "enabled": COLORS["success"],
        "disabled": COLORS["text_faint"],
    }
    return mapping.get((status or "").lower(), COLORS["text_faint"])


def status_zh(status: str) -> str:
    """状态 -> 中文文案（任务状态 + 账号任务状态）。"""
    mapping = {
        "completed": "完成",
        "partial": "作品不足",
        "empty": "无作品",
        "failed": "失败",
        "skipped": "已跳过",
        "running": "运行中",
        "pending": "等待中",
        "stopped": "已停止",
        "ok": "正常",
        "unknown": "未知",
        "enabled": "启用",
        "disabled": "禁用",
    }
    return mapping.get((status or "").lower(), status or "")


# 状态 -> 表格行 tag 名（用于 Treeview.tag_configure 着色）
_STATUS_TAGS = {
    "completed": "ok", "ok": "ok", "enabled": "ok", "success": "ok",
    "partial": "partial", "stopped": "partial", "warning": "partial",
    "failed": "failed", "danger": "failed", "error": "failed",
    "running": "running", "info": "running",
    "pending": "dim", "skipped": "muted", "empty": "muted",
    "unknown": "muted", "disabled": "muted",
}


def status_tag(status: str) -> str:
    """状态 -> 行 tag（颜色分组）。"""
    return _STATUS_TAGS.get((status or "").lower(), "dim")


def truncate_middle(s: str, max_len: int = 40) -> str:
    """URL 等长字符串中间截断，保留首尾，避免表格被撑爆。"""
    s = str(s or "")
    if len(s) <= max_len:
        return s
    head = (max_len - 3) // 2
    tail = (max_len - 3) - head
    return s[:head] + "…" + s[-tail:]


class StatCard(ctk.CTkFrame):
    """仪表盘统计卡片：大数字 + 说明文字。"""

    def __init__(self, master, label: str, value="0", color: Optional[str] = None,
                 icon: str = "", **kw):
        kw.setdefault("fg_color", COLORS["surface"])
        kw.setdefault("corner_radius", RADIUS["lg"])
        super().__init__(master, **kw)
        self.grid_columnconfigure(0, weight=1)
        self._value_lbl = ctk.CTkLabel(self, text=str(value), font=FONT["number"],
                                       text_color=color or COLORS["text"], anchor="w")
        self._value_lbl.grid(row=0, column=0, sticky="w", padx=18, pady=(16, 0))
        label_text = f"{icon} {label}" if icon else label
        self._label_lbl = ctk.CTkLabel(self, text=label_text, font=FONT["secondary"],
                                       text_color=COLORS["text_dim"], anchor="w")
        self._label_lbl.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 16))

    def set_value(self, value) -> None:
        self._value_lbl.configure(text=str(value))


class ScrollableTable(ctk.CTkFrame):
    """基于 ttk.Treeview 的深色可滚动表格。

    iid 由调用方指定（通常为 account_id / video_id / task_id），
    选中项通过 selected_iids() 直接拿到业务 ID。
    支持状态行着色（insert_status）、行点击（on_row_click）。
    """

    def __init__(self, master, columns: List[str], headers: Optional[List[str]] = None,
                 height: int = 10, on_select: Optional[Callable[[List[str]], None]] = None,
                 on_row_click: Optional[Callable[[str], None]] = None,
                 stretch_cols: Optional[set] = None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.columns = columns
        headers = headers or columns
        self._stretch = stretch_cols or set(columns)

        wrap = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=RADIUS["md"])
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(wrap, columns=columns, show="headings",
                                 height=height, selectmode="extended")
        for col, hdr in zip(columns, headers):
            self.tree.heading(col, text=hdr)
            anchor = "center" if col in ("collect_count", "count", "status", "check") else "w"
            self.tree.column(col, anchor=anchor, minwidth=50, width=120,
                             stretch=(col in self._stretch))

        # 状态行着色 tag（Treeview 行 tag，非 ttk Style）
        self._tag_colors = {
            "ok": COLORS["success"], "partial": COLORS["warning"],
            "failed": COLORS["danger"], "running": COLORS["info"],
            "muted": COLORS["text_faint"], "dim": COLORS["text_dim"],
        }
        for tag, color in self._tag_colors.items():
            self.tree.tag_configure(tag, foreground=color)

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._on_select = on_select
        self._on_row_click = on_row_click
        self.tree.bind("<<TreeviewSelect>>", self._handle_select)
        if on_row_click:
            self.tree.bind("<ButtonRelease-1>", self._handle_click)

    def _handle_select(self, _e) -> None:
        if self._on_select:
            self._on_select(self.selected_iids())

    def _handle_click(self, event) -> None:
        if not self._on_row_click:
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self._on_row_click(iid)

    def clear(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)

    def insert(self, iid, values, tags=()) -> None:
        self.tree.insert("", "end", iid=str(iid), values=values, tags=tags)

    def insert_status(self, iid, values, status: str) -> None:
        """按状态插入并自动着色该行。"""
        self.insert(iid, values, tags=(status_tag(status),))

    def delete(self, iid) -> None:
        if self.tree.exists(str(iid)):
            self.tree.delete(str(iid))

    def get_values(self, iid) -> tuple:
        return self.tree.item(str(iid))["values"] if self.tree.exists(str(iid)) else ()

    def set_values(self, iid, values) -> None:
        if self.tree.exists(str(iid)):
            self.tree.item(str(iid), values=values)

    def selected_iids(self) -> List[str]:
        return list(self.tree.selection())

    def all_iids(self) -> List[str]:
        return list(self.tree.get_children())

    def row_count(self) -> int:
        return len(self.tree.get_children())

    def set_widths(self, widths: dict) -> None:
        for col, w in widths.items():
            if w:
                self.tree.column(col, width=w)

    def set_all_selected(self, selected: bool) -> None:
        """全选 / 全不选。"""
        self.tree.selection_set(self.all_iids()) if selected else \
            self.tree.selection_remove(self.all_iids())


# ---- 弹窗路由：阻塞 MessageBox -> 全局 Toast / 样式化对话框 ----
def _toast_target(master):
    try:
        return master.winfo_toplevel() if master is not None else None
    except Exception:
        return None


def _toast(master, message: str, title: str = "", level: str = "info",
           duration: int = 3200) -> bool:
    """若顶层窗口挂有 ToastManager 则路由到 Toast，返回是否已处理。"""
    top = _toast_target(master)
    mgr = getattr(top, "toast", None)
    if mgr is not None:
        mgr.show(message, title=title, level=level, duration=duration)
        return True
    return False


def show_info(master, title: str, message: str) -> None:
    """信息提示：优先 Toast（非阻塞），无 Toast 时回退 messagebox。"""
    if _toast(master, message, title=title, level="info"):
        return
    from tkinter import messagebox
    messagebox.showinfo(title, message, parent=master)


def show_success(master, message: str, title: str = "") -> None:
    """成功提示（Toast）。"""
    if _toast(master, message, title=title or "成功", level="success"):
        return
    show_info(master, title or "成功", message)


def show_error(master, title: str, message: str) -> None:
    """错误提示：Toast（error 级别，更长驻留）。"""
    if _toast(master, message, title=title, level="error", duration=6000):
        return
    from tkinter import messagebox
    messagebox.showerror(title, message, parent=master)


def ask_confirm(master, title: str, message: str, danger: bool = False) -> bool:
    """统一确认弹窗（样式化），返回是否确认。"""
    from .components.dialog import confirm
    return confirm(master, title, message, danger=danger)


def section_title(master, text: str) -> ctk.CTkLabel:
    """区块标题。"""
    return ctk.CTkLabel(master, text=text, font=FONT["section"],
                        text_color=COLORS["text"], anchor="w")
