"""历史记录页面：任务列表 + 详情查看 + 复制/导出。"""
from __future__ import annotations

from tkinter import filedialog

import customtkinter as ctk

from app.export.export_service import ExportService
from app.export.models import AccountStat, ExportRow

from ..theme import COLORS, FONT
from ..widgets import ScrollableTable, status_zh
from ..components import EmptyState, PageHeader
from .base_page import BasePage


class HistoryPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._current_task = None
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "历史记录", "查看历次采集任务与明细")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))

        self._task_table = ScrollableTable(
            self,
            columns=["task_id", "target_date", "accounts", "actual", "success", "fail", "status", "created_at"],
            headers=["任务ID", "日期", "账号数", "实际", "成功", "失败", "状态", "创建时间"],
            height=9,
            stretch_cols={"task_id", "created_at"},
            on_select=self._on_select_task,
        )
        self._task_table.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))

        # 详情区
        detail = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=12)
        detail.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 20))
        detail.grid_columnconfigure(0, weight=1)
        detail.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(detail, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        head.grid_columnconfigure(0, weight=1)
        self._detail_lbl = ctk.CTkLabel(head, text="选择任务查看详情", font=FONT["section"],
                                        text_color=COLORS["text"], anchor="w")
        self._detail_lbl.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(head, text="复制全部链接", width=120, height=32, fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"], command=self._copy_task).grid(
            row=0, column=1, padx=4)
        ctk.CTkButton(head, text="导出 TXT", width=90, height=32, fg_color=COLORS["surface_alt"],
                      command=lambda: self._export_task("txt")).grid(row=0, column=2, padx=4)
        ctk.CTkButton(head, text="导出 XLSX", width=90, height=32, fg_color=COLORS["surface_alt"],
                      command=lambda: self._export_task("xlsx")).grid(row=0, column=3, padx=4)

        self._detail_table = ScrollableTable(
            detail,
            columns=["username", "target", "actual", "status", "error"],
            headers=["账号", "目标", "实际", "状态", "说明"],
            height=8,
            stretch_cols={"error"},
        )
        self._detail_table.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))

        # 空状态
        self._empty = EmptyState(
            self, title="暂无历史任务", subtitle="完成一次采集后，任务记录会显示在这里",
            icon="history", action_text="去采集任务", action_command=lambda: self._goto("collect"))
        self._empty.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))
        self._empty.grid_remove()

    def _goto(self, key):
        if hasattr(self.window, "show_page"):
            self.window.show_page(key)

    def refresh(self) -> None:
        tasks = self.ctx.result_service.list_tasks(limit=50)
        self._task_table.clear()
        for r in tasks:
            self._task_table.insert_status(r["task_id"], (
                r["task_id"], r["target_date"] or "", r["account_count"],
                r["actual_total"], r["success_count"], r["fail_count"],
                status_zh(r["status"]), r["created_at"] or "",
            ), r["status"])
        self._current_task = None
        self._detail_table.clear()
        self._detail_lbl.configure(text="选择任务查看详情")
        if not tasks:
            self._task_table.grid_remove()
            self._empty.grid()
        else:
            self._empty.grid_remove()
            self._task_table.grid()

    def _on_select_task(self, sel) -> None:
        if not sel:
            return
        task_id = sel[0]
        self._current_task = task_id
        detail = self.ctx.result_service.task_detail(task_id)
        task = detail["task"]
        self._detail_lbl.configure(
            text=f"{task_id} · {task['target_date']} · 实际 {task['actual_total']} 条"
                 f"（成功 {task['success_count']} / 失败 {task['fail_count']}）")
        self._detail_table.clear()
        for a in detail["accounts"]:
            self._detail_table.insert_status(a["account_id"], (
                f"@{a['username']}", a["target_count"], a["actual_count"],
                status_zh(a["status"]), a["error_reason"] or "",
            ), a["status"])

    def _copy_task(self) -> None:
        if not self._current_task:
            self.toast("请先选择一个任务", title="提示", level="warning")
            return
        text = self.ctx.result_service.task_video_urls(self._current_task)
        if not text:
            self.toast("该任务没有作品链接", title="提示", level="warning")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        n = len([x for x in text.splitlines() if x.strip()])
        self.toast(f"已复制 {n} 条链接", title="已复制", level="success")

    def _export_task(self, kind: str) -> None:
        if not self._current_task:
            self.toast("请先选择一个任务", title="提示", level="warning")
            return
        detail = self.ctx.result_service.task_detail(self._current_task)
        videos = detail["videos"]
        if not videos:
            self.toast("该任务没有作品数据", title="提示", level="warning")
            return
        rows = [ExportRow(
            account=v["account_id"], username=v["username"], video_id=v["video_id"],
            publish_time=v["publish_time"] or "", publish_date=v["publish_date"] or "",
            video_url=v["video_url"], collect_time=v["first_collect_time"] or "",
            task_id=v["first_task_id"] or "", status=v["status"],
        ) for v in videos]

        if kind == "txt":
            path = filedialog.asksaveasfilename(
                title="导出 TXT", defaultextension=".txt",
                initialfile=f"{self._current_task}.txt",
                filetypes=[("文本文件", "*.txt")])
            if not path:
                return
            ExportService.export_txt(rows, path, mode="urls")
        else:
            path = filedialog.asksaveasfilename(
                title="导出 XLSX", defaultextension=".xlsx",
                initialfile=f"{self._current_task}.xlsx",
                filetypes=[("Excel 文件", "*.xlsx")])
            if not path:
                return
            stats = [AccountStat(account=s["account"], username=s["username"],
                                 target_count=s.get("target_count", 0),
                                 actual_count=s["actual_count"], status=s.get("status", ""))
                     for s in self.ctx.result_service.account_stats(videos)]
            ExportService.export_xlsx(rows, stats, path)
        self.toast(f"已导出到：\n{path}", title="导出成功", level="success", duration=5000)
