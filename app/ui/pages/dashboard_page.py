"""仪表盘页面：统计卡片（去重后）+ 当前任务实时区 + 最近任务列表。"""
from __future__ import annotations

from datetime import datetime

import customtkinter as ctk

from ..theme import COLORS, FONT
from ..widgets import ScrollableTable, StatCard, status_zh
from ..components import EmptyState, PageHeader
from .base_page import BasePage


class DashboardPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._refresh_after = None
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "仪表盘", "账号作品链接采集概览")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))
        self.header.add_action("开始采集", lambda: self._goto("collect"), kind="primary")

        # 未完成任务横幅（实时区）
        self._banner = ctk.CTkFrame(self, fg_color=COLORS["warning_soft"],
                                    corner_radius=10)
        self._banner.grid(row=1, column=0, sticky="ew", padx=24, pady=(6, 8))
        self._banner.grid_columnconfigure(0, weight=1)
        self._banner_label = ctk.CTkLabel(self._banner, text="", font=FONT["body"],
                                          text_color=COLORS["warning"], anchor="w")
        self._banner_label.grid(row=0, column=0, sticky="w", padx=14, pady=10)
        self._banner_btn = ctk.CTkButton(
            self._banner, text="前往采集任务", width=120, height=32,
            fg_color=COLORS["warning"], hover_color=COLORS["warning_hover"],
            font=FONT["button"], command=lambda: self._goto("collect"))
        self._banner_btn.grid(row=0, column=1, padx=(0, 10), pady=8)

        # 统计卡片行
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.grid(row=2, column=0, sticky="ew", padx=24)
        for i in range(5):
            cards.grid_columnconfigure(i, weight=1, uniform="card")
        self._card_accounts = StatCard(cards, "账号总数", "0", COLORS["primary"])
        self._card_enabled = StatCard(cards, "已启用账号", "0", COLORS["accent"])
        self._card_videos = StatCard(cards, "累计作品链接", "0", COLORS["success"])
        self._card_today = StatCard(cards, "今日新增链接", "0", COLORS["info"])
        self._card_tasks = StatCard(cards, "历史任务", "0", COLORS["text"])
        for i, c in enumerate([
            self._card_accounts, self._card_enabled, self._card_videos,
            self._card_today, self._card_tasks,
        ]):
            c.grid(row=0, column=i, sticky="ew", padx=6, pady=6)

        # 最近任务
        self._section = ctk.CTkLabel(self, text="最近任务", font=FONT["section"],
                                     text_color=COLORS["text"], anchor="w")
        self._section.grid(row=3, column=0, sticky="w", padx=24, pady=(16, 8))
        self._table = ScrollableTable(
            self,
            columns=["task_id", "target_date", "accounts", "target", "actual", "status", "created_at"],
            headers=["任务ID", "记录日期", "账号数", "目标", "实际", "状态", "创建时间"],
            height=10,
            stretch_cols={"task_id", "created_at"},
            on_row_click=self._on_task_click,
        )
        self._table.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 20))
        self.grid_rowconfigure(4, weight=1)

        # 首屏引导（无账号时显示三步流程）
        self._onboarding = self._build_onboarding()
        self._onboarding.grid(row=2, column=0, rowspan=3, sticky="nsew", padx=24, pady=12)
        self._onboarding.grid_remove()

    def _build_onboarding(self):
        """三步流程引导卡片（添加账号 → 采集 → 复制）。"""
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid_columnconfigure(0, weight=1)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.grid(row=0, column=0, pady=30)

        ctk.CTkLabel(inner, text="欢迎使用 TikTok 作品链接采集器",
                     font=FONT["page_title"], text_color=COLORS["text"]).pack(pady=(0, 4))
        ctk.CTkLabel(inner, text="三步即可批量拿到你所有账号的作品链接",
                     font=FONT["secondary"], text_color=COLORS["text_dim"]).pack(pady=(0, 28))

        steps = [
            ("1", "添加账号", "导入 TikTok 主页链接", "去添加账号", "accounts", COLORS["primary"]),
            ("2", "开始采集", "选账号设数量，后台串行采集", "去采集任务", "collect", COLORS["accent"]),
            ("3", "复制链接", "一键复制 / 导出全部链接", "去采集结果", "results", COLORS["success"]),
        ]
        cards = ctk.CTkFrame(inner, fg_color="transparent")
        cards.pack()
        for num, title, desc, btn, page, color in steps:
            card = ctk.CTkFrame(cards, fg_color=COLORS["surface"], corner_radius=12,
                                width=240, height=190)
            card.pack(side="left", padx=10)
            card.pack_propagate(False)
            ctk.CTkLabel(card, text=num, font=("Microsoft YaHei UI", 30, "bold"),
                         text_color=color, anchor="w").pack(anchor="w", padx=18, pady=(16, 2))
            ctk.CTkLabel(card, text=title, font=FONT["section"],
                         text_color=COLORS["text"], anchor="w").pack(anchor="w", padx=18)
            ctk.CTkLabel(card, text=desc, font=FONT["secondary"],
                         text_color=COLORS["text_dim"], anchor="w").pack(
                anchor="w", padx=18, pady=(2, 12))
            ctk.CTkButton(card, text=btn, width=120, height=32, fg_color=color,
                          command=lambda p=page: self._goto(p)).pack(anchor="w", padx=18)
        return box

    # ---- 生命周期 ----
    def refresh(self) -> None:
        self._reload()
        self._start_auto_refresh()

    def on_leave(self) -> None:
        self._stop_auto_refresh()

    def _start_auto_refresh(self) -> None:
        self._stop_auto_refresh()
        self._refresh_after = self.after(3000, self._auto_refresh)

    def _auto_refresh(self) -> None:
        if self.winfo_viewable():
            self._reload()
        self._refresh_after = self.after(3000, self._auto_refresh)

    def _stop_auto_refresh(self) -> None:
        if self._refresh_after is not None:
            try:
                self.after_cancel(self._refresh_after)
            except Exception:
                pass
            self._refresh_after = None

    def _goto(self, key: str) -> None:
        win = self.window
        if hasattr(win, "show_page"):
            win.show_page(key)

    # ---- 数据 ----
    def _reload(self) -> None:
        db = self.ctx.db
        today = datetime.now().strftime("%Y-%m-%d")

        total_accounts = db.count_accounts()
        self._card_accounts.set_value(total_accounts)
        en = db.query("SELECT COUNT(*) c FROM accounts WHERE enabled=1")
        self._card_enabled.set_value(en[0]["c"] if en else 0)
        self._card_videos.set_value(db.count_videos())
        today_new = db.query(
            "SELECT COUNT(*) c FROM videos WHERE substr(first_collect_time,1,10)=?", (today,))
        self._card_today.set_value(today_new[0]["c"] if today_new else 0)
        tasks = db.query("SELECT COUNT(*) c FROM collect_tasks")
        self._card_tasks.set_value(tasks[0]["c"] if tasks else 0)

        # 未完成任务横幅
        self._update_banner()

        # 最近任务
        self._table.clear()
        for r in db.list_tasks(limit=10):
            self._table.insert_status(r["task_id"], (
                r["task_id"], r["target_date"] or "", r["account_count"],
                r["target_total"], r["actual_total"], status_zh(r["status"]),
                r["created_at"] or "",
            ), r["status"])

        # 空状态切换
        if total_accounts == 0:
            self._section.grid_remove()
            self._table.grid_remove()
            self._onboarding.grid()
        else:
            self._onboarding.grid_remove()
            self._section.grid()
            self._table.grid()

    def _update_banner(self) -> None:
        task = self.ctx.db.find_unfinished_task()
        if task:
            self._banner_label.configure(
                text=f"有未完成任务 {task['task_id']}（{task['target_date'] or '—'}）尚未完成，可继续采集。")
            self._banner.grid()
        else:
            self._banner.grid_remove()

    def _on_task_click(self, iid) -> None:
        self._goto("history")
