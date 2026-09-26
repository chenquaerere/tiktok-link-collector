"""采集任务页面：日期/数量选择、账号勾选、开始采集、进度、暂停/继续/停止。"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

import customtkinter as ctk

from app.core.models import Account

from ..theme import COLORS, FONT
from ..widgets import ScrollableTable, status_zh
from ..components import EmptyState, PageHeader
from ..notify import notify_failure, notify_success
from .base_page import BasePage


class CollectPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._thread = None
        self._running = False
        self._paused = False
        self._done_ids = set()      # 本次会话内已完成账号（用于「继续」跳过）
        self._failed_accounts = []  # 最近一次运行的失败账号结果（用于重试）
        self._checkboxes = {}
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "采集任务", "选择账号 → 设置数量 → 开始串行采集")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))

        # 参数区
        cfg = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=12)
        cfg.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))
        cfg.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(cfg, text="记录日期", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=0, padx=(16, 6), pady=10)
        self._date_entry = ctk.CTkEntry(cfg, width=120, font=FONT["body"],
                                        placeholder_text="YYYY-MM-DD")
        self._date_entry.grid(row=0, column=1, padx=4, pady=10)
        ctk.CTkButton(cfg, text="今天", width=56, height=32, fg_color=COLORS["surface_alt"],
                      command=self._set_today).grid(row=0, column=2, padx=3)
        ctk.CTkButton(cfg, text="昨天", width=56, height=32, fg_color=COLORS["surface_alt"],
                      command=self._set_yesterday).grid(row=0, column=3, padx=3)

        ctk.CTkLabel(cfg, text="每账号最新条数", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=4, padx=(18, 6))
        self._count_entry = ctk.CTkEntry(cfg, width=64, font=FONT["body"])
        self._count_entry.grid(row=0, column=5, padx=4, sticky="w")
        ctk.CTkButton(cfg, text="应用到已选", width=100, height=32, fg_color=COLORS["surface_alt"],
                      command=self._apply_count_to_selected).grid(row=0, column=6, padx=(4, 6))

        ctk.CTkLabel(cfg, text="账号间隔(秒)", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=1, column=0, padx=(16, 6), pady=(0, 12))
        self._interval_entry = ctk.CTkEntry(cfg, width=64, font=FONT["body"])
        self._interval_entry.grid(row=1, column=1, padx=4, pady=(0, 12))
        self._interval_entry.insert(0, str(self.ctx.config.get("account_interval_seconds", 4)))

        self._start_btn = ctk.CTkButton(cfg, text="开始采集", width=104, height=38,
                                        fg_color=COLORS["primary"], command=self._start)
        self._start_btn.grid(row=0, column=7, padx=(16, 6), pady=12)
        self._pause_btn = ctk.CTkButton(cfg, text="暂停", width=64, height=38,
                                        fg_color=COLORS["warning"],
                                        text_color="#141824",
                                        text_color_disabled="#2c2416",
                                        hover_color=COLORS["warning_hover"],
                                        state="disabled",
                                        command=self._pause)
        self._pause_btn.grid(row=0, column=8, padx=3)
        self._resume_btn = ctk.CTkButton(cfg, text="继续", width=64, height=38,
                                         fg_color=COLORS["accent"],
                                         text_color="#141824",
                                         text_color_disabled="#12302f",
                                         hover_color=COLORS["accent_hover"],
                                         state="disabled", command=self._resume)
        self._resume_btn.grid(row=0, column=9, padx=3)
        self._stop_btn = ctk.CTkButton(cfg, text="停止", width=64, height=38,
                                       fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"],
                                       state="disabled", command=self._stop)
        self._stop_btn.grid(row=0, column=10, padx=(3, 16))

        # 进度区
        self._prog_frame = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=12)
        self._prog_frame.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 12))
        self._prog_frame.grid_columnconfigure(0, weight=1)
        self._progress = ctk.CTkProgressBar(self._prog_frame, height=14)
        self._progress.set(0)
        self._progress.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        self._status_lbl = ctk.CTkLabel(self._prog_frame, text="等待开始", font=FONT["body"],
                                        text_color=COLORS["text_dim"], anchor="w")
        self._status_lbl.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 16))

        # 账号选择 + 结果 左右布局
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 20))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        left = ctk.CTkFrame(body, fg_color=COLORS["surface"], corner_radius=12)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text="选择账号", font=FONT["section"],
                     text_color=COLORS["text"], anchor="w").grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ops = ctk.CTkFrame(left, fg_color="transparent")
        ops.grid(row=1, column=0, sticky="ew", padx=12)
        ctk.CTkButton(ops, text="全选", width=58, height=28, fg_color=COLORS["surface_alt"],
                      command=lambda: self._check_all(True)).pack(side="left", padx=2)
        ctk.CTkButton(ops, text="反选", width=58, height=28, fg_color=COLORS["surface_alt"],
                      command=lambda: self._check_all(False)).pack(side="left", padx=2)
        ctk.CTkButton(ops, text="恢复未完成", width=92, height=28, fg_color=COLORS["surface_alt"],
                      command=self._check_resume).pack(side="left", padx=2)
        self._selected_lbl = ctk.CTkLabel(ops, text="已选 0/0", font=FONT["secondary"],
                                          text_color=COLORS["accent"], anchor="e")
        self._selected_lbl.pack(side="right", padx=4)
        self._account_scroll = ctk.CTkScrollableFrame(left, width=300, fg_color="transparent")
        self._account_scroll.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 12))
        left.grid_rowconfigure(2, weight=1)

        self._account_empty = EmptyState(
            left, title="暂无启用账号", subtitle="请先到「账号管理」添加并启用账号",
            icon="account", action_text="去账号管理", action_command=lambda: self._goto("accounts"))
        self._account_empty.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 12))
        self._account_empty.grid_remove()

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        # 失败重试栏（有失败账号时显示）
        self._retry_bar = ctk.CTkFrame(right, fg_color=COLORS["danger_soft"], corner_radius=10)
        self._retry_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._retry_bar.grid_columnconfigure(0, weight=1)
        self._retry_label = ctk.CTkLabel(self._retry_bar, text="", font=FONT["secondary"],
                                         text_color=COLORS["danger"], anchor="w")
        self._retry_label.grid(row=0, column=0, sticky="w", padx=12, pady=8)
        self._retry_btn = ctk.CTkButton(self._retry_bar, text="重试失败账号", width=120, height=30,
                                        fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"],
                                        command=self._retry_failed)
        self._retry_btn.grid(row=0, column=1, padx=(0, 10), pady=6)
        self._retry_bar.grid_remove()

        self._result_table = ScrollableTable(
            right,
            columns=["username", "target", "actual", "status", "error"],
            headers=["账号", "目标", "实际", "状态", "说明"],
            height=16,
            stretch_cols={"error"},
        )
        self._result_table.grid(row=1, column=0, sticky="nsew")

    def _goto(self, key):
        if hasattr(self.window, "show_page"):
            self.window.show_page(key)

    # ---- 日期/数量 ----
    def refresh(self) -> None:
        self._date_entry.delete(0, "end")
        self._date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self._count_entry.delete(0, "end")
        self._count_entry.insert(0, str(self.ctx.config.get("default_collect_count", 4)))
        self._interval_entry.delete(0, "end")
        self._interval_entry.insert(0, str(self.ctx.config.get("account_interval_seconds", 4)))
        self._load_accounts()

    def _set_today(self) -> None:
        self._date_entry.delete(0, "end")
        self._date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))

    def _set_yesterday(self) -> None:
        self._date_entry.delete(0, "end")
        self._date_entry.insert(0, (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))

    def _load_accounts(self) -> None:
        for w in self._account_scroll.winfo_children():
            w.destroy()
        self._checkboxes.clear()
        rows = self.ctx.account_service.list(enabled_only=True)
        for i, r in enumerate(rows):
            cb = ctk.CTkCheckBox(
                self._account_scroll, text=f"@{r['username']}",
                font=FONT["body"], text_color=COLORS["text"],
                checkbox_width=20, checkbox_height=20,
                command=self._update_selected_count,
            )
            cb.grid(row=i, column=0, sticky="w", padx=(8, 2), pady=3)
            cb.select()
            cnt = ctk.CTkEntry(self._account_scroll, width=48, height=28,
                               font=FONT["secondary"], justify="center")
            cnt.insert(0, str(r["collect_count"]))
            cnt.grid(row=i, column=1, sticky="e", padx=(2, 8), pady=3)
            self._checkboxes[r["account_id"]] = (cb, cnt, r)
        self._account_scroll.grid_columnconfigure(1, weight=0)
        if rows:
            self._account_empty.grid_remove()
            self._account_scroll.grid()
        else:
            self._account_scroll.grid_remove()
            self._account_empty.grid()
        self._update_selected_count()

    def _update_selected_count(self) -> None:
        total = len(self._checkboxes)
        sel = sum(1 for cb, _, _ in self._checkboxes.values() if cb.get())
        self._selected_lbl.configure(text=f"已选 {sel}/{total}")

    def _check_all(self, select_all: bool) -> None:
        for cb, _, _ in self._checkboxes.values():
            if select_all:
                cb.select()
            else:
                cb.deselect()
        self._update_selected_count()

    def _selected_accounts(self, exclude_done: bool = False):
        out = []
        for aid, (cb, cnt, r) in self._checkboxes.items():
            if not cb.get():
                continue
            if exclude_done and aid in self._done_ids:
                continue
            out.append(Account(
                account_id=aid, username=r["username"], profile_url=r["profile_url"],
                collect_count=self._account_count(cnt),
            ))
        return out

    def _account_count(self, entry) -> int:
        try:
            return max(0, int(entry.get().strip()))
        except ValueError:
            return self._target_count()

    def _apply_count_to_selected(self) -> None:
        n = self._target_count()
        applied = 0
        for cb, cnt, _ in self._checkboxes.values():
            if cb.get():
                cnt.delete(0, "end")
                cnt.insert(0, str(n))
                applied += 1
        self._status_lbl.configure(
            text=f"已将「每账号数量 = {n}」应用到 {applied} 个已选账号",
            text_color=COLORS["accent"])

    def _target_count(self) -> int:
        try:
            return max(0, int(self._count_entry.get().strip()))
        except ValueError:
            return self.ctx.config.get("default_collect_count", 4)

    def _target_date(self) -> str:
        d = self._date_entry.get().strip()
        return d or datetime.now().strftime("%Y-%m-%d")

    def _account_interval(self) -> float:
        try:
            return max(0.0, float(self._interval_entry.get().strip()))
        except ValueError:
            return float(self.ctx.config.get("account_interval_seconds", 4.0))

    # ---- 控制 ----
    def _start(self) -> None:
        if self._running:
            return
        self._done_ids.clear()
        self._launch(self._selected_accounts())

    def _resume(self) -> None:
        if self._running:
            return
        accounts = self._selected_accounts(exclude_done=True)
        if accounts:
            self._launch(accounts)
            return
        self._resume_from_db()

    def _resume_from_db(self) -> None:
        task = self.ctx.db.find_unfinished_task()
        if not task:
            self.toast("没有未完成的任务", title="提示", level="info")
            return
        unfinished = self.ctx.db.unfinished_account_ids(task["task_id"])
        if not unfinished:
            self.ctx.db.update_task(task["task_id"], status="completed")
            self.toast("没有未完成的任务", title="提示", level="info")
            return
        if not self.confirm("恢复未完成任务",
                            f"检测到未完成任务 {task['task_id']}（{task['target_date']}），"
                            f"还有 {len(unfinished)} 个账号未完成。\n继续采集这些账号？"):
            return
        self._select_only(unfinished)
        accounts = self._accounts_by_ids(unfinished)
        if accounts:
            self._launch(accounts)
        else:
            self.toast("未完成账号已不存在于账号池", title="提示", level="warning")

    def _check_resume(self) -> None:
        task = self.ctx.db.find_unfinished_task()
        if not task:
            self.toast("没有未完成的任务", title="提示", level="info")
            return
        unfinished = self.ctx.db.unfinished_account_ids(task["task_id"])
        if not unfinished:
            self.ctx.db.update_task(task["task_id"], status="completed")
            self.toast("没有未完成的任务", title="提示", level="info")
            return
        self.toast(f"任务 {task['task_id']}（{task['target_date']}）还有 "
                   f"{len(unfinished)} 个账号未完成，点击「继续」可恢复。",
                   title="检测到未完成任务", level="warning", duration=6000)

    def _select_only(self, account_ids) -> None:
        ids = set(account_ids)
        for aid, (cb, _, _) in self._checkboxes.items():
            if aid in ids:
                cb.select()
            else:
                cb.deselect()

    def _accounts_by_ids(self, ids):
        out = []
        for aid in ids:
            r = self.ctx.db.get_account(aid)
            if r:
                out.append(Account(
                    account_id=aid, username=r["username"], profile_url=r["profile_url"],
                    collect_count=r["collect_count"],
                ))
        return out

    def _retry_failed(self) -> None:
        """重试最近一次运行中失败的账号（成功账号的记录不受影响）。"""
        if self._running:
            return
        if not self._failed_accounts:
            self.toast("没有需要重试的失败账号", title="提示", level="info")
            return
        accounts = []
        for r in self._failed_accounts:
            row = self.ctx.db.get_account(r.account_id)
            if not row:
                continue
            accounts.append(Account(
                account_id=r.account_id, username=row["username"],
                profile_url=row["profile_url"], collect_count=r.target_count,
            ))
        if not accounts:
            self.toast("失败账号已不存在于账号池", title="提示", level="warning")
            return
        self._launch(accounts)

    def _launch(self, accounts) -> None:
        if not accounts:
            self.toast("请先勾选要采集的账号", title="提示", level="warning")
            return
        # 把本次设置的每账号数量写回数据库，让「单独调数量」持久化
        for acc in accounts:
            self.ctx.account_service.update(acc.account_id, collect_count=acc.collect_count)
        # 账号间隔快捷设置即时生效
        self.ctx.config.set("account_interval_seconds", self._account_interval())
        self.ctx.save_config()
        self.ctx.reset_engine()

        target_date = self._target_date()
        engine = self.ctx.build_engine()
        engine.reset()

        self._running = True
        self._paused = False
        self._start_btn.configure(state="disabled")
        self._pause_btn.configure(state="normal", text="暂停")
        self._resume_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._progress.set(0)
        self._result_table.clear()
        self._retry_bar.grid_remove()
        self._failed_accounts = []
        self._status_lbl.configure(text="任务启动中…", text_color=COLORS["accent"])
        self.set_status("采集中…")

        self._thread = threading.Thread(
            target=self._run_worker, args=(accounts, target_date), daemon=True)
        self._thread.start()

    def _run_worker(self, accounts, target_date) -> None:
        engine = self.ctx.build_engine()

        def on_progress(idx, total_n, username, status, detail):
            def apply():
                if total_n > 0:
                    self._progress.set((idx + 1) / total_n)
                extra = detail.get("collected", "") if isinstance(detail, dict) and "collected" in detail else ""
                self._status_lbl.configure(
                    text=f"[{idx + 1}/{total_n}] @{username} — {_stage_zh(status)} {extra}",
                    text_color=COLORS["text_dim"])
            self.ui_call(apply)

        try:
            summary = engine.run(accounts, target_date, on_progress=on_progress)
            self.ui_call(self._on_done, summary)
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.exception("采集任务异常")
            self.ui_call(self._on_error, str(exc))

    def _on_done(self, summary) -> None:
        self._running = False
        self._start_btn.configure(state="normal")
        self._pause_btn.configure(state="disabled", text="暂停")
        self._stop_btn.configure(state="disabled")
        self._result_table.clear()
        remaining = 0
        self._failed_accounts = []
        for r in summary["accounts"]:
            self._result_table.insert_status(r.account_id, (
                f"@{r.username}", r.target_count, r.actual_count,
                status_zh(r.status), r.error_reason or "",
            ), r.status)
            if r.status in ("completed", "partial", "empty"):
                self._done_ids.add(r.account_id)
            else:
                remaining += 1
                if r.status == "failed":
                    self._failed_accounts.append(r)

        # 失败账号：显示重试栏（区分「需登录」与其它失败）
        if self._failed_accounts:
            login_cnt = sum(1 for r in self._failed_accounts
                            if r.diagnostics.get("login_required"))
            hint = (f"{len(self._failed_accounts)} 个账号失败，"
                    + (f"其中 {login_cnt} 个需登录（先手动登录再重试）"
                       if login_cnt else "可点击右侧重试"))
            self._retry_label.configure(text=hint)
            self._retry_bar.grid()
        else:
            self._retry_bar.grid_remove()

        n = len(summary["accounts"])
        msg = (f"共 {n} 个账号：完成 {summary['completed']} / 部分 {summary['partial']} / "
               f"无作品 {summary['empty']} / 失败 {summary['failed']}；"
               f"实际采到 {summary['actual_total']} 条链接，新增 {summary['new_videos']} 条")
        color = COLORS["success"]
        level = "success"
        if self._paused or summary.get("status") == "stopped":
            msg = "已暂停/停止。已采数据已保留。" + msg
            color = COLORS["warning"]
            level = "warning"
        if remaining > 0:
            self._resume_btn.configure(state="normal")
            msg += f"；还有 {remaining} 个账号未完成，可点「继续」"
        self._progress.set(1)
        self._status_lbl.configure(text=msg, text_color=color)
        self.set_status("采集结束")
        self.toast(msg, title="采集结束", level=level, duration=6000)
        # 声音提示（默认开）
        if self.ctx.config.get("notify_sound", True):
            if summary.get("failed") or summary.get("login_required"):
                notify_failure()
            else:
                notify_success()

    def _on_error(self, err) -> None:
        self._running = False
        self._start_btn.configure(state="normal")
        self._pause_btn.configure(state="disabled", text="暂停")
        self._resume_btn.configure(state="disabled")
        self._stop_btn.configure(state="disabled")
        self._status_lbl.configure(text=f"采集出错：{err}", text_color=COLORS["danger"])
        self.set_status("采集出错")
        if self.ctx.config.get("notify_sound", True):
            notify_failure()
        self.show_error_dialog(
            "采集失败", err,
            "建议：检查网络与代理设置，确认浏览器可正常访问 TikTok 后重试。\n详细错误已写入日志。")

    def _pause(self) -> None:
        self._paused = True
        self.ctx.build_engine().request_stop()
        self._pause_btn.configure(state="disabled")
        self._status_lbl.configure(text="暂停中：当前账号采完即停，已采数据已保留",
                                   text_color=COLORS["warning"])

    def _stop(self) -> None:
        self._paused = False
        self.ctx.build_engine().request_stop()
        self._status_lbl.configure(text="正在停止…", text_color=COLORS["danger"])


def _stage_zh(status: str) -> str:
    return {
        "collecting": "采集中",
        "completed": "完成",
        "partial": "部分",
        "empty": "无作品",
        "failed": "失败",
        "skipped": "跳过",
        "running": "运行中",
    }.get(status, status)
