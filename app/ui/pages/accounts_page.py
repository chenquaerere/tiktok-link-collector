"""账号管理页面：搜索 / 筛选 / 批量导入 / 启停 / 删除 / 编辑数量。"""
from __future__ import annotations

import csv
import os
from tkinter import filedialog

import customtkinter as ctk

from ..theme import COLORS, FONT
from ..widgets import ScrollableTable, status_zh
from ..components import EmptyState, PageHeader
from .base_page import BasePage


class AccountsPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "账号管理", "管理你的 TikTok 账号池")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))

        # 顶部：搜索 + 状态筛选
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=24)
        bar.grid_columnconfigure(1, weight=1)

        # 注意：CTkEntry 绑定 textvariable 后 placeholder 会被空值覆盖而不显示，
        # 因此这里不绑变量，改为 KeyRelease 直读。
        self.search = ctk.CTkEntry(bar, placeholder_text="搜索账号 / 备注…",
                                   font=FONT["body"], height=38)
        self.search.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.search.bind("<KeyRelease>", lambda e: self._render())

        self.status_filter = ctk.CTkComboBox(
            bar, values=["全部状态", "仅启用", "仅禁用"], width=120,
            font=FONT["body"], command=lambda _: self._render())
        self.status_filter.set("全部状态")
        self.status_filter.grid(row=0, column=2, padx=4)

        ctk.CTkButton(bar, text="批量导入", width=100, height=38,
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      command=self._import_dialog).grid(row=0, column=3, padx=4)

        # 添加行
        addbar = ctk.CTkFrame(self, fg_color="transparent")
        addbar.grid(row=2, column=0, sticky="ew", padx=24, pady=(8, 8))
        addbar.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(addbar, placeholder_text="输入主页链接或 @用户名，回车添加",
                                  font=FONT["body"], height=38)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self._add())
        ctk.CTkButton(addbar, text="添加", width=80, height=38,
                      command=self._add).grid(row=0, column=1)

        # 操作行
        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.grid(row=3, column=0, sticky="ew", padx=24, pady=(6, 8))
        self._selected_lbl = ctk.CTkLabel(ops, text="已选 0 项", font=FONT["secondary"],
                                          text_color=COLORS["text_dim"])
        self._selected_lbl.grid(row=0, column=0, sticky="w")
        self._total_lbl = ctk.CTkLabel(ops, text="", font=FONT["secondary"],
                                       text_color=COLORS["text_faint"])
        self._total_lbl.grid(row=0, column=1, sticky="w", padx=(12, 0))
        ctk.CTkButton(ops, text="全选", width=70, height=32, fg_color=COLORS["surface_alt"],
                      command=lambda: self._select_toggle(True)).grid(row=0, column=2, padx=3)
        ctk.CTkButton(ops, text="反选", width=70, height=32, fg_color=COLORS["surface_alt"],
                      command=self._invert).grid(row=0, column=3, padx=3)
        ctk.CTkButton(ops, text="启用", width=70, height=32, fg_color=COLORS["success"],
                      hover_color=COLORS["success_hover"],
                      command=lambda: self._set_enabled(True)).grid(row=0, column=4, padx=3)
        ctk.CTkButton(ops, text="禁用", width=70, height=32, fg_color=COLORS["warning"],
                      hover_color=COLORS["warning_hover"],
                      command=lambda: self._set_enabled(False)).grid(row=0, column=5, padx=3)
        ctk.CTkButton(ops, text="编辑数量", width=90, height=32, fg_color=COLORS["surface_alt"],
                      command=self._edit_count).grid(row=0, column=6, padx=3)
        ctk.CTkButton(ops, text="删除", width=70, height=32, fg_color=COLORS["danger"],
                      hover_color=COLORS["danger_hover"], command=self._delete).grid(
            row=0, column=7, padx=3)

        # 表格
        self.table = ScrollableTable(
            self,
            columns=["username", "profile_url", "collect_count", "login_status",
                     "last_collect_time", "enabled", "remark"],
            headers=["账号", "主页", "采集数量", "登录状态", "最后采集", "状态", "备注"],
            height=16,
            stretch_cols={"profile_url", "remark"},
            on_select=lambda sel: self._selected_lbl.configure(text=f"已选 {len(sel)} 项"),
        )
        self.table.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 20))
        self.grid_rowconfigure(4, weight=1)

        self._empty = EmptyState(
            self, title="暂无账号", subtitle="在下方输入 TikTok 主页链接或 @用户名 添加",
            icon="account", action_text="去采集任务", action_command=lambda: self._goto("collect"))
        self._empty.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 20))
        self._empty.grid_remove()

    def _goto(self, key):
        if hasattr(self.window, "show_page"):
            self.window.show_page(key)

    # ---- 数据 ----
    def refresh(self) -> None:
        self.search.delete(0, "end")
        # CTkEntry._is_focused 初始即 True（从未聚焦过），delete() 内部的
        # 占位符恢复分支不会触发，这里显式调用内部方法恢复占位符文本
        self.search._activate_placeholder()
        self.status_filter.set("全部状态")
        self._render()

    def _render(self) -> None:
        rows = self.ctx.account_service.list()
        q = self.search.get().strip().lower()
        f = self.status_filter.get()
        filtered = []
        for r in rows:
            if q:
                hay = f"{r['username']} {r['remark'] or ''} {r['profile_url']}".lower()
                if q not in hay:
                    continue
            if f == "仅启用" and not r["enabled"]:
                continue
            if f == "仅禁用" and r["enabled"]:
                continue
            filtered.append(r)

        self.table.clear()
        for r in filtered:
            self.table.insert_status(r["account_id"], (
                f"@{r['username']}", r["profile_url"], r["collect_count"],
                status_zh(r["login_status"]), r["last_collect_time"] or "",
                "启用" if r["enabled"] else "禁用", r["remark"] or "",
            ), "enabled" if r["enabled"] else "disabled")
        self._total_lbl.configure(text=f"共 {len(rows)} 个账号 · 显示 {len(filtered)}")
        self._selected_lbl.configure(text="已选 0 项")
        if not rows:
            self.table.grid_remove()
            self._empty.grid()
        else:
            self._empty.grid_remove()
            self.table.grid()

    # ---- 操作 ----
    def _add(self) -> None:
        raw = self.entry.get().strip()
        if not raw:
            return
        ok, msg = self.ctx.account_service.add(raw)
        self.entry.delete(0, "end")
        if ok:
            self.toast(msg, title="添加成功", level="success")
        else:
            self.toast(msg, title="添加失败", level="error", duration=5000)
        self._render()

    def _select_toggle(self, select_all: bool) -> None:
        self.table.set_all_selected(select_all)
        self._selected_lbl.configure(
            text=f"已选 {len(self.table.selected_iids())} 项")

    def _invert(self) -> None:
        all_iids = set(self.table.all_iids())
        sel = set(self.table.tree.selection())
        for iid in all_iids - sel:
            self.table.tree.selection_add(iid)
        for iid in sel:
            self.table.tree.selection_remove(iid)
        self._selected_lbl.configure(text=f"已选 {len(self.table.tree.selection())} 项")

    def _set_enabled(self, enabled: bool) -> None:
        sel = self.table.selected_iids()
        if not sel:
            self.toast("请先选中账号", title="提示", level="warning")
            return
        for aid in sel:
            self.ctx.account_service.set_enabled(aid, enabled)
        self.toast(f"已{'启用' if enabled else '禁用'} {len(sel)} 个账号",
                   title="完成", level="success")
        self._render()

    def _delete(self) -> None:
        sel = self.table.selected_iids()
        if not sel:
            self.toast("请先选中账号", title="提示", level="warning")
            return
        if not self.confirm("确认删除",
                            f"确定删除选中的 {len(sel)} 个账号？\n其作品与采集日志将一并删除。",
                            danger=True):
            return
        for aid in sel:
            self.ctx.account_service.delete(aid)
        self.toast(f"已删除 {len(sel)} 个账号", title="完成", level="success")
        self._render()

    def _edit_count(self) -> None:
        sel = self.table.selected_iids()
        if not sel:
            self.toast("请先选中一个或多个账号再设置采集数量", title="提示", level="warning")
            return
        dialog = ctk.CTkInputDialog(
            text=f"为选中的 {len(sel)} 个账号统一设置采集数量：",
            title="批量设置采集数量")
        val = dialog.get_input()
        if not val:
            return
        try:
            n = int(str(val).strip())
        except ValueError:
            self.toast("请输入整数", title="格式错误", level="error")
            return
        if n < 0:
            n = 0
        for aid in sel:
            self.ctx.account_service.update(aid, collect_count=n)
        self.toast(f"已为 {len(sel)} 个账号设置采集数量 = {n}", title="完成", level="success")
        self._render()

    # ---- 批量导入 ----
    def _import_dialog(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("批量导入账号")
        win.geometry("620x520")
        win.configure(fg_color=COLORS["surface"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="每行一个主页链接或 @用户名", font=FONT["secondary"],
                     text_color=COLORS["text_dim"], anchor="w").pack(
            anchor="w", padx=20, pady=(18, 6))
        text = ctk.CTkTextbox(win, font=FONT["body"], height=300)
        text.pack(fill="both", expand=True, padx=20, pady=6)

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=10)

        def from_file():
            path = filedialog.askopenfilename(
                title="选择文件", filetypes=[
                    ("文本/CSV", "*.txt *.csv *.tsv"),
                    ("Excel", "*.xlsx *.xls"),
                    ("所有文件", "*.*"),
                ])
            if not path:
                return
            lines = _read_import_file(path)
            if lines:
                text.delete("1.0", "end")
                text.insert("1.0", "\n".join(lines))
            else:
                self.toast("未能从该文件读取到有效账号", title="读取失败", level="error")

        ctk.CTkButton(btns, text="从文件读取", width=110, fg_color=COLORS["surface_alt"],
                      command=from_file).pack(side="left", padx=4)

        def do_import():
            raw = text.get("1.0", "end")
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return
            result = self.ctx.account_service.import_many(lines)
            imported = len(result["imported"])
            failed = result["failed"]
            skipped = len(result["skipped"])
            win.destroy()
            self._render()
            if failed:
                detail = "；".join(f"{f['input'][:30]}：{f['error']}" for f in failed[:5])
                self.toast(f"成功 {imported} / 跳过 {skipped} / 失败 {len(failed)}",
                           title="导入完成", level="warning", duration=6000)
                self.toast(detail, title="失败详情", level="error", duration=6000)
            else:
                self.toast(f"成功导入 {imported} 个，跳过重复 {skipped} 个",
                           title="导入完成", level="success")

        ctk.CTkButton(btns, text="导入", width=90, fg_color=COLORS["primary"],
                      command=do_import).pack(side="right", padx=4)
        ctk.CTkButton(btns, text="取消", width=70, fg_color=COLORS["surface_alt"],
                      command=win.destroy).pack(side="right", padx=4)


def _read_import_file(path: str):
    """从 TXT/CSV/XLSX 读取账号行（容错，返回非空用户名/URL 行）。"""
    lines = []
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".xlsx", ".xls"):
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell and str(cell).strip():
                        lines.append(str(cell).strip())
                        break
            wb.close()
        else:
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                for row in reader:
                    for cell in row:
                        if cell and cell.strip():
                            lines.append(cell.strip())
                            break
    except Exception:
        return []
    return lines
