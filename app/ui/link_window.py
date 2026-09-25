"""链接文本面板 / 链接窗口：把作品链接以纯文本列出，方便鼠标框选、逐条复制。

设计目标（对应「用鼠标选取链接进行复制」的需求）：
- `LinkTextPanel`：可嵌入任意容器的组件（结果页内嵌用）。
- `LinkWindow`：独立 Toplevel 弹窗，包裹 LinkTextPanel。
- 原生 tk.Text（只读）+ 深色滚动条；等宽字体，每条链接后跟一个空行。
- 支持鼠标拖选 / 双击选词 / Ctrl+C 复制 / Ctrl+A 全选 / 右键菜单。
- 支持「纯链接 / 账号分组」两种显示模式切换。
- 「复制选中」：无选区时自动退化为复制全部。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List, Optional

import customtkinter as ctk

from .theme import COLORS, FONT_BODY, FONT_SMALL

# URL 用等宽字体，便于逐字符框选、对比。
_FONT_URL = ("Consolas", 12)
_FONT_MENU = ("Microsoft YaHei UI", 11)


class LinkTextPanel(ctk.CTkFrame):
    """可嵌入的链接文本面板：工具栏 + 只读文本区。"""

    def __init__(self, master, urls: Optional[List[str]] = None,
                 grouped_text: Optional[str] = None, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self._urls = [u for u in (urls or []) if u and u.strip()]
        self._grouped = grouped_text or ""
        self._mode = "urls"  # urls / grouped
        self._hint_after = None
        self._build()
        self._fill()

    # ---- 布局 ----
    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top.grid_columnconfigure(4, weight=1)

        self._mode_menu = ctk.CTkOptionMenu(
            top, width=100, height=30, font=FONT_SMALL,
            values=["纯链接", "账号分组"],
            fg_color=COLORS["surface_alt"], button_color=COLORS["primary"],
            button_hover_color=COLORS["primary_hover"],
            dropdown_fg_color=COLORS["surface_alt"],
            dropdown_hover_color=COLORS["border"],
            text_color=COLORS["text"],
            command=self._on_mode_change,
        )
        self._mode_menu.set("纯链接")
        self._mode_menu.grid(row=0, column=0, padx=(0, 6))

        ctk.CTkButton(top, text="复制选中", width=76, height=30,
                      fg_color=COLORS["accent"], hover_color="#2fb0b0",
                      command=self.copy_selected).grid(row=0, column=1, padx=3)
        ctk.CTkButton(top, text="复制全部", width=76, height=30,
                      fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
                      command=self.copy_all).grid(row=0, column=2, padx=3)

        self._count_lbl = ctk.CTkLabel(top, text="", font=FONT_SMALL,
                                       text_color=COLORS["text_dim"], anchor="e")
        self._count_lbl.grid(row=0, column=4, sticky="e")

        body = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=10)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.text = tk.Text(
            body, wrap="none", bg=COLORS["surface"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["primary"], selectforeground="#ffffff",
            relief="flat", bd=0, padx=12, pady=10,
            font=_FONT_URL, state="disabled", highlightthickness=0,
            undo=False, cursor="xterm",
        )
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        xsb = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        # 快捷键 + 右键菜单（只读态下 Ctrl+C 需手动实现）
        self.text.bind("<Control-c>", lambda _e: (self.copy_selected(), "break")[1])
        self.text.bind("<Control-a>", lambda _e: (self.select_all(), "break")[1])
        self.text.bind("<Button-3>", self._popup)

        self._menu = tk.Menu(self, tearoff=0,
                             bg=COLORS["surface_alt"], fg=COLORS["text"],
                             activebackground=COLORS["primary"],
                             activeforeground="#ffffff",
                             font=_FONT_MENU, bd=0)
        self._menu.add_command(label="复制选中", command=self.copy_selected)
        self._menu.add_command(label="复制全部", command=self.copy_all)
        self._menu.add_separator()
        self._menu.add_command(label="全选", command=self.select_all)

    # ---- 数据 ----
    def set_data(self, urls: List[str], grouped_text: Optional[str] = None) -> None:
        self._urls = [u for u in urls if u and u.strip()]
        self._grouped = grouped_text or ""
        self._fill()

    def _on_mode_change(self, choice: str) -> None:
        self._mode = "grouped" if choice == "账号分组" else "urls"
        self._fill()

    def _fill(self) -> None:
        if self._mode == "grouped" and self._grouped:
            content = self._grouped
        else:
            content = "\n\n".join(self._urls)
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if content:
            self.text.insert("1.0", content)
        self.text.configure(state="disabled")
        self._count_lbl.configure(text=f"共 {len(self._urls)} 条链接")

    # ---- 复制 / 选择 ----
    def _selection_text(self) -> str:
        try:
            sel = self.text.get("sel.first", "sel.last")
            if sel and sel.strip():
                return sel
        except tk.TclError:
            pass
        return ""

    def copy_selected(self) -> None:
        sel = self._selection_text()
        if not sel:
            sel = self.text.get("1.0", "end-1c")
        if not sel or not sel.strip():
            self._hint("没有可复制的链接")
            return
        self.clipboard_clear()
        self.clipboard_append(sel)
        lines = len([x for x in sel.splitlines() if x.strip()])
        self._hint(f"已复制 {lines} 条链接")

    def copy_all(self) -> None:
        self.select_all()
        self.copy_selected()

    def select_all(self) -> None:
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")
        self.text.focus_set()

    def _popup(self, event) -> None:
        self._menu.tk_popup(event.x_root, event.y_root)
        self._menu.grab_release()

    def _hint(self, msg: str) -> None:
        self._count_lbl.configure(text=msg, text_color=COLORS["accent"])
        if self._hint_after is not None:
            self.after_cancel(self._hint_after)
        self._hint_after = self.after(
            1800, lambda: self._count_lbl.configure(
                text=f"共 {len(self._urls)} 条链接", text_color=COLORS["text_dim"]))


class LinkWindow(tk.Toplevel):
    """独立链接窗口：包裹 LinkTextPanel 的弹窗。"""

    def __init__(self, master, urls: List[str],
                 grouped_text: Optional[str] = None,
                 title: str = "作品链接"):
        super().__init__(master)
        self.title(title)
        self.geometry("760x660")
        self.minsize(540, 420)
        self.configure(bg=COLORS["bg"])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        panel = LinkTextPanel(self, urls=urls, grouped_text=grouped_text,
                              fg_color="transparent")
        panel.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.panel = panel
