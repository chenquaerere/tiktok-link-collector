"""采集结果页面：按日期/账号/状态筛选、复制链接、导出 TXT/CSV/XLSX。"""
from __future__ import annotations

import threading
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk
import tkinter as tk

from app.export.export_service import ExportService
from app.export.models import AccountStat, ExportRow

from ..theme import COLORS, FONT
from ..link_window import LinkTextPanel, LinkWindow
from ..widgets import ScrollableTable, truncate_middle
from ..components import EmptyState, PageHeader, LoadingState
from .base_page import BasePage


class ResultsPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._rows = []
        self._url_by_id = {}   # video_id -> 完整 URL（点击复制 / hover 用）
        self._loading = None
        self._tooltip = None
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "采集结果", "查看、筛选、复制与导出已采集的作品链接")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))

        # 筛选 + 操作
        bar = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=12)
        bar.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))
        ctk.CTkLabel(bar, text="发布日期", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=0, padx=(16, 6), pady=12)
        self._date_entry = ctk.CTkEntry(bar, width=130, font=FONT["body"],
                                        placeholder_text="留空=全部")
        self._date_entry.grid(row=0, column=1, padx=4)
        ctk.CTkLabel(bar, text="账号", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=2, padx=(14, 6))
        self._account_menu = ctk.CTkComboBox(bar, width=150, font=FONT["body"],
                                             values=["全部账号"])
        self._account_menu.set("全部账号")
        self._account_menu.grid(row=0, column=3, padx=4)
        ctk.CTkLabel(bar, text="状态", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=4, padx=(14, 6))
        self._status_menu = ctk.CTkComboBox(bar, width=110, font=FONT["body"],
                                            values=["全部状态"], command=lambda _: self._render())
        self._status_menu.set("全部状态")
        self._status_menu.grid(row=0, column=5, padx=4)
        ctk.CTkButton(bar, text="查询", width=72, height=34, fg_color=COLORS["primary"],
                      command=self._query).grid(row=0, column=6, padx=(12, 12))

        ctk.CTkButton(bar, text="链接窗口", width=90, height=34, fg_color=COLORS["primary"],
                      hover_color=COLORS["primary_hover"],
                      command=self._open_link_window).grid(row=0, column=7, padx=4)
        ctk.CTkButton(bar, text="复制全部", width=90, height=34, fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"], command=self._copy_all).grid(
            row=0, column=8, padx=4)
        self._export_menu = ctk.CTkOptionMenu(
            bar, width=150, height=34, font=FONT["body"],
            values=["导出 TXT(纯URL)", "导出 TXT(分组)", "导出 CSV", "导出 XLSX"],
            command=lambda _: self._export())
        self._export_menu.set("导出…")
        self._export_menu.grid(row=0, column=9, padx=(8, 16))

        # 结果表格（元信息，占上半部分）
        self._table = ScrollableTable(
            self,
            columns=["username", "video_id", "publish_time", "publish_date", "video_url", "status"],
            headers=["账号", "作品ID", "发布时间", "发布日期", "作品URL", "状态"],
            height=8,
            stretch_cols={"video_url"},
            on_row_click=self._on_row_click,
        )
        self._table.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self.grid_rowconfigure(2, weight=3)
        # 悬停显示完整 URL
        self._table.tree.bind("<Motion>", self._on_hover, add="+")
        self._table.tree.bind("<Leave>", lambda _e: self._hide_tooltip(), add="+")

        # 内嵌链接文本区（占下半部分，可直接框选复制）
        self._link_panel = LinkTextPanel(self, urls=[], fg_color=COLORS["surface"],
                                         corner_radius=12)
        self._link_panel.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 12))
        self.grid_rowconfigure(3, weight=2)

        self._count_lbl = ctk.CTkLabel(self, text="共 0 条", font=FONT["secondary"],
                                       text_color=COLORS["text_dim"], anchor="w")
        self._count_lbl.grid(row=4, column=0, sticky="w", padx=24, pady=(0, 12))

        # 空状态
        self._empty = EmptyState(
            self, title="暂无作品链接", subtitle="先去「采集任务」采集，或调整筛选条件",
            icon="result", action_text="去采集任务", action_command=lambda: self._goto("collect"))
        self._empty.grid(row=2, column=0, rowspan=2, sticky="nsew", padx=24, pady=(0, 8))
        self._empty.grid_remove()

    def _goto(self, key):
        if hasattr(self.window, "show_page"):
            self.window.show_page(key)

    # ---- 数据 ----
    def refresh(self) -> None:
        values = ["全部账号"] + [f"@{r['username']}" for r in self.ctx.account_service.list()]
        self._account_menu.configure(values=values)
        if self._account_menu.get() not in values:
            self._account_menu.set("全部账号")
        self._query()

    def _query(self) -> None:
        date = self._date_entry.get().strip() or None
        acc = self._account_menu.get()
        account_id = None
        if acc and acc != "全部账号":
            account_id = acc.lstrip("@")
        self._rows = self.ctx.result_service.query_videos(
            publish_date=date, account_id=account_id)
        self._rebuild_status_options()
        self._render()

    def _rebuild_status_options(self) -> None:
        statuses = sorted({r["status"] for r in self._rows if r["status"]})
        values = ["全部状态"] + statuses
        cur = self._status_menu.get()
        self._status_menu.configure(values=values)
        if cur not in values:
            self._status_menu.set("全部状态")

    def _render(self) -> None:
        f = self._status_menu.get()
        rows = [r for r in self._rows if f == "全部状态" or r["status"] == f]

        self._table.clear()
        self._url_by_id.clear()
        for r in rows:
            full = r["video_url"]
            self._url_by_id[r["video_id"]] = full
            self._table.insert(r["video_id"], (
                f"@{r['username']}", r["video_id"], r["publish_time"] or "",
                r["publish_date"] or "", truncate_middle(full, 46), r["status"],
            ))
        self._count_lbl.configure(text=f"共 {len(rows)} 条"
                                       + (f"（筛选自 {len(self._rows)} 条）" if f != "全部状态" else ""))

        urls = [u for u in self.ctx.result_service.to_url_text(rows).split("\n") if u.strip()]
        grouped = self.ctx.result_service.to_grouped_text(rows)
        self._link_panel.set_data(urls, grouped_text=grouped)

        if not self._rows:
            self._table.grid_remove()
            self._link_panel.grid_remove()
            self._empty.grid()
        else:
            self._empty.grid_remove()
            self._table.grid()
            self._link_panel.grid()

    # ---- 点击复制 + hover 提示 ----
    def _on_row_click(self, iid) -> None:
        full = self._url_by_id.get(iid)
        if not full:
            return
        self.clipboard_clear()
        self.clipboard_append(full)
        self.toast(f"已复制 1 条链接", title="已复制", level="success")

    def _on_hover(self, event) -> None:
        iid = self._table.tree.identify_row(event.y)
        col = self._table.tree.identify_column(event.x)
        if not iid or col != "#5":  # video_url 是第 5 列
            self._hide_tooltip()
            return
        full = self._url_by_id.get(iid)
        if not full:
            self._hide_tooltip()
            return
        self._show_tooltip(event, full)

    def _show_tooltip(self, event, text) -> None:
        self._hide_tooltip()
        top = self.winfo_toplevel()
        tip = tk.Toplevel(top)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        lbl = ctk.CTkLabel(tip, text=text, font=FONT["mono"],
                           fg_color=COLORS["surface_alt"], corner_radius=6,
                           text_color=COLORS["text"], padx=10, pady=6)
        lbl.pack()
        x = event.x_root + 16
        y = event.y_root + 12
        tip.geometry(f"+{x}+{y}")
        self._tooltip = tip

    def _hide_tooltip(self) -> None:
        if self._tooltip is not None:
            try:
                self._tooltip.destroy()
            except Exception:
                pass
            self._tooltip = None

    # ---- 导出（后台线程）----
    def _export_rows(self):
        return [ExportRow(
            account=r["account_id"], username=r["username"], video_id=r["video_id"],
            publish_time=r["publish_time"] or "", publish_date=r["publish_date"] or "",
            video_url=r["video_url"], collect_time=r["first_collect_time"] or "",
            task_id=r["first_task_id"] or "", status=r["status"],
        ) for r in self._rows]

    def _export(self) -> None:
        choice = self._export_menu.get()
        self._export_menu.set("导出…")
        if choice not in ("导出 TXT(纯URL)", "导出 TXT(分组)", "导出 CSV", "导出 XLSX"):
            return
        if not self._rows:
            self.toast("没有可导出的数据", title="提示", level="warning")
            return
        rows = self._export_rows()
        date = self._date_entry.get().strip() or datetime.now().strftime("%Y-%m-%d")

        ext_map = {
            "导出 TXT(纯URL)": (".txt", "文本文件", "*.txt"),
            "导出 TXT(分组)": (".txt", "文本文件", "*.txt"),
            "导出 CSV": (".csv", "CSV 文件", "*.csv"),
            "导出 XLSX": (".xlsx", "Excel 文件", "*.xlsx"),
        }
        ext, fname, pattern = ext_map[choice]
        path = filedialog.asksaveasfilename(
            title="导出", defaultextension=ext,
            initialfile=f"作品链接_{date}{ext}",
            filetypes=[(fname, pattern)])
        if not path:
            return

        self._show_loading("正在导出…")

        def worker():
            try:
                if choice == "导出 TXT(纯URL)":
                    ExportService.export_txt(rows, path, mode="urls")
                elif choice == "导出 TXT(分组)":
                    ExportService.export_txt(rows, path, mode="grouped")
                elif choice == "导出 CSV":
                    ExportService.export_csv(rows, path)
                else:
                    stats = [AccountStat(account=s["account"], username=s["username"],
                                         target_count=s.get("target_count", 0),
                                         actual_count=s["actual_count"],
                                         status=s.get("status", ""))
                             for s in self.ctx.result_service.account_stats(self._rows)]
                    ExportService.export_xlsx(rows, stats, path)
                self.after(0, lambda: self._on_export_done(path, len(rows)))
            except Exception as exc:  # noqa: BLE001
                self.ctx.logger.exception("导出失败")
                self.after(0, lambda: self._on_export_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_loading(self, text) -> None:
        self._hide_loading()
        self._loading = LoadingState(self, text=text, fg_color=COLORS["surface"],
                                     corner_radius=12)
        self._loading.grid(row=2, column=0, rowspan=2, sticky="nsew",
                           padx=24, pady=(0, 8))
        self._loading.lift()

    def _hide_loading(self) -> None:
        if self._loading is not None:
            try:
                self._loading.stop()
                self._loading.destroy()
            except Exception:
                pass
            self._loading = None

    def _on_export_done(self, path, n) -> None:
        self._hide_loading()
        self.toast(f"已导出 {n} 条到：\n{path}", title="导出成功", level="success", duration=5000)

    def _on_export_error(self, err) -> None:
        self._hide_loading()
        self.show_error_dialog("导出失败", err, "建议：确认目标目录可写，或更换导出路径。")

    # ---- 链接窗口 ----
    def _open_link_window(self) -> None:
        if not self._rows:
            self.toast("没有可展示的链接，请先查询或采集", title="提示", level="warning")
            return
        urls = [u for u in self.ctx.result_service.to_url_text(self._rows).split("\n") if u.strip()]
        grouped = self.ctx.result_service.to_grouped_text(self._rows)
        win = LinkWindow(self, urls, grouped_text=grouped)
        win.transient(self.winfo_toplevel())

    # ---- 复制 ----
    def _copy_all(self) -> None:
        text = self.ctx.result_service.to_url_text(self._rows)
        if not text:
            self.toast("没有可复制的链接", title="提示", level="warning")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        n = len([x for x in text.splitlines() if x.strip()])
        self.toast(f"已复制 {n} 条链接到剪贴板", title="已复制", level="success")
