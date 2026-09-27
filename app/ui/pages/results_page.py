"""采集结果页面：按日期/账号/状态筛选、复制链接、导出 TXT/CSV/XLSX。"""
from __future__ import annotations

import threading
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk
import tkinter as tk

from app.export.export_service import ExportService
from app.export.models import AccountStat, ExportRow
from app.core.regions import account_label, account_id_from_label

from ..theme import COLORS, FONT
from ..link_window import LinkTextPanel, LinkWindow
from ..widgets import ScrollableTable, truncate_middle
from ..components import EmptyState, PageHeader, LoadingState
from .base_page import BasePage

# 数据范围下拉项
SCOPE_SESSION = "本次采集"
SCOPE_ALL = "全部历史"


class ResultsPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._rows = []
        self._url_by_id = {}   # video_id -> 完整 URL（点击复制 / hover 用）
        self._loading = None
        self._tooltip = None
        self._clear_armed = False   # 「确认清空」二次确认态
        # 数据范围默认「本次采集」：结果页只展示本次任务采到的链接，
        # 而不是库里全部历史（否则只采 1 个账号 3 条，却会看到一堆旧链接）。
        # 打开程序时若本次尚未采集，链接区保持空白。
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "采集结果", "查看、筛选、复制与导出已采集的作品链接")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))
        # 操作按钮放页头右侧动作区（筛选行太挤放不下，也正好利用头部空间）
        self._clear_btn = self.header.add_action(
            "清空链接", self._clear_links, width=92,
            color=COLORS["danger"], hover=COLORS["danger_hover"])
        self.header.add_action("复制全部", self._copy_all, width=92,
                               color=COLORS["accent"], hover=COLORS["accent_hover"])
        self.header.add_action("链接窗口", self._open_link_window, width=92)
        self._export_menu = ctk.CTkOptionMenu(
            self.header.actions, width=140, height=34, font=FONT["body"],
            values=["导出 TXT(纯URL)", "导出 TXT(分组)", "导出 CSV", "导出 XLSX"],
            command=lambda _: self._export())
        self._export_menu.set("导出…")
        self._export_menu.pack(side="left", padx=(4, 0))

        # 筛选行
        bar = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=12)
        bar.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))
        ctk.CTkLabel(bar, text="范围", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=0, padx=(16, 6), pady=12)
        self._scope_menu = ctk.CTkComboBox(
            bar, width=112, font=FONT["body"], values=[SCOPE_SESSION, SCOPE_ALL],
            command=lambda _: self._on_scope_changed())
        self._scope_menu.set(SCOPE_SESSION)
        self._scope_menu.grid(row=0, column=1, padx=4)
        ctk.CTkLabel(bar, text="发布日期", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=2, padx=(14, 6))
        self._date_entry = ctk.CTkEntry(bar, width=130, font=FONT["body"],
                                        placeholder_text="留空=全部")
        self._date_entry.grid(row=0, column=3, padx=4)
        ctk.CTkLabel(bar, text="账号", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=4, padx=(14, 6))
        self._account_menu = ctk.CTkComboBox(bar, width=150, font=FONT["body"],
                                             values=["全部账号"])
        self._account_menu.set("全部账号")
        self._account_menu.grid(row=0, column=5, padx=4)
        ctk.CTkLabel(bar, text="状态", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=6, padx=(14, 6))
        self._status_menu = ctk.CTkComboBox(bar, width=110, font=FONT["body"],
                                            values=["全部状态"], command=lambda _: self._render())
        self._status_menu.set("全部状态")
        self._status_menu.grid(row=0, column=7, padx=4)
        ctk.CTkButton(bar, text="查询", width=72, height=34, fg_color=COLORS["primary"],
                      command=self._on_query_clicked).grid(row=0, column=8, padx=(12, 16))

        # 结果表格（元信息，占上半部分）
        self._table = ScrollableTable(
            self,
            columns=["username", "video_id", "collect_time", "publish_time",
                     "publish_date", "video_url", "status"],
            headers=["账号", "作品ID", "采集时间", "发布时间", "发布日期", "作品URL", "状态"],
            height=8,
            stretch_cols={"video_url"},
            on_row_click=self._on_row_click,
        )
        self._table.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self._table.set_widths({"collect_time": 148, "publish_time": 148,
                                "publish_date": 96})
        self.grid_rowconfigure(2, weight=3)
        # 悬停显示完整 URL
        self._table.tree.bind("<Motion>", self._on_hover, add="+")
        self._table.tree.bind("<Leave>", lambda _e: self._hide_tooltip(), add="+")

        # 内嵌链接文本区（占下半部分，可直接框选复制）
        self._link_panel = LinkTextPanel(self, urls=[], fg_color=COLORS["surface"],
                                         corner_radius=12)
        self._link_panel.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 12))
        self.grid_rowconfigure(3, weight=2)

        # 底部统计行：条数 + 最近采集时间（绿色高亮，让「刚采完」一眼可见）
        meta = ctk.CTkFrame(self, fg_color="transparent")
        meta.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 12))
        self._count_lbl = ctk.CTkLabel(meta, text="共 0 条", font=FONT["secondary"],
                                       text_color=COLORS["text_dim"], anchor="w")
        self._count_lbl.pack(side="left")
        self._latest_lbl = ctk.CTkLabel(meta, text="", font=FONT["body_strong"],
                                        text_color=COLORS["success"], anchor="w")
        self._latest_lbl.pack(side="left", padx=(14, 0))

        # 空状态
        self._empty = EmptyState(
            self, title="暂无作品链接", subtitle="先去「采集任务」采集，或调整筛选条件",
            icon="result", action_text="去采集任务", action_command=lambda: self._goto("collect"))
        self._empty.grid(row=2, column=0, rowspan=2, sticky="nsew", padx=24, pady=(0, 8))
        self._empty.grid_remove()

        # 启动态：本次会话还没采集过 → 链接区保持空白，
        # 避免把「上次采集的链接」误当成本次结果（用户明确要求）。
        self._idle = EmptyState(
            self, title="本次尚未采集",
            subtitle="链接区已清空，采集完成后会自动显示本次采到的链接\n"
                     "如需查看以前采集过的链接，把上方「范围」切到「全部历史」",
            icon="result", action_text="去采集任务", action_command=lambda: self._goto("collect"))
        self._idle.grid(row=2, column=0, rowspan=2, sticky="nsew", padx=24, pady=(0, 8))
        self._idle.grid_remove()

    def _goto(self, key):
        if hasattr(self.window, "show_page"):
            self.window.show_page(key)

    # ---- 数据 ----
    def refresh(self) -> None:
        values = ["全部账号"] + [account_label(r) for r in self.ctx.account_service.list()]
        self._account_menu.configure(values=values)
        if self._account_menu.get() not in values:
            self._account_menu.set("全部账号")
        # 打开程序后默认「本次采集」范围，且本次未采集 → 链接区保持空白，
        # 不显示上次运行残留的链接（用户明确要求）。
        if self._in_session_scope() and not getattr(self.ctx, "collected_this_session", False):
            self._show_idle()
            return
        self._query()

    def _in_session_scope(self) -> bool:
        """当前数据范围是否为「本次采集」。"""
        return self._scope_menu.get() == SCOPE_SESSION

    def _on_scope_changed(self) -> None:
        """切换数据范围：本次采集 ↔ 全部历史。"""
        if self._in_session_scope() and not getattr(self.ctx, "collected_this_session", False):
            self._show_idle()
            return
        self._query()

    def _on_query_clicked(self) -> None:
        """按当前筛选条件重新查询（数据范围由「范围」下拉决定）。"""
        self._on_scope_changed()

    def _show_idle(self) -> None:
        """清空结果区并显示「本次尚未采集」提示（不动数据库）。"""
        self._rows = []
        self._url_by_id.clear()
        try:
            self._table.clear()
            self._table.grid_remove()
            self._link_panel.set_data([], grouped_text="")
            self._link_panel.grid_remove()
        except Exception:  # noqa: BLE001
            pass
        self._count_lbl.configure(text="本次尚未采集")
        self._latest_lbl.configure(text="")
        self._empty.grid_remove()
        self._idle.grid()

    def _query(self) -> None:
        self._idle.grid_remove()
        date = self._date_entry.get().strip() or None
        acc = self._account_menu.get()
        account_id = None
        if acc and acc != "全部账号":
            account_id = account_id_from_label(acc)

        # 数据范围：默认只看「本次任务」采到的链接 —— 只选 1 个账号采 3 条时，
        # 就不会把库里其它账号的历史链接一起列出来。
        task_id = None
        if self._in_session_scope():
            task_id = getattr(self.ctx, "last_task_id", "") or None
            if not task_id:
                self._show_idle()          # 本次没采过 → 保持空白
                return
        self._rows = self.ctx.result_service.query_videos(
            publish_date=date, account_id=account_id, task_id=task_id)
        # 按「采集时间」倒序：刚采的排最前（同批采集时间相同，再按发布时间倒序）
        self._rows.sort(
            key=lambda r: ((r["first_collect_time"] or ""), (r["publish_time"] or "")),
            reverse=True)
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
                f"@{r['username']}", r["video_id"],
                r["first_collect_time"] or "", r["publish_time"] or "",
                r["publish_date"] or "", truncate_middle(full, 46), r["status"],
            ))
        self._count_lbl.configure(text=f"共 {len(rows)} 条"
                                       + (f"（筛选自 {len(self._rows)} 条）" if f != "全部状态" else ""))
        # 最近采集时间节点（绿色）——一眼看出这批数据是什么时候采的
        times = [r["first_collect_time"] for r in self._rows if r["first_collect_time"]]
        self._latest_lbl.configure(text=(f"最近采集 {max(times)}" if times else ""))

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
        # 列索引按列名动态取，避免以后插入新列导致悬停提示错位
        try:
            url_sel = f"#{self._table.columns.index('video_url') + 1}"
        except ValueError:
            self._hide_tooltip()
            return
        if not iid or col != url_sel:
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
                self.ui_call(self._on_export_done, path, len(rows))
            except Exception as exc:  # noqa: BLE001
                self.ctx.logger.exception("导出失败")
                self.ui_call(self._on_export_error, str(exc))

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

    # ---- 清空（内联二次确认，不依赖模态弹窗） ----
    def _clear_links(self) -> None:
        """清空作品链接：第一次点击进入「确认」态，3 秒内再点一次才执行。

        旧版用 CTkToplevel 模态确认框：弹窗一旦被主窗口遮住，grab 会卡住
        主界面，用户看到的就是「点了没反应、链接还在」（且无任何日志）。
        改为按钮内联确认后彻底消除这个不确定性。
        """
        date = self._date_entry.get().strip() or None
        acc = self._account_menu.get()
        account_id = None if (not acc or acc == "全部账号") else account_id_from_label(acc)

        scope = []
        if date:
            scope.append(f"发布日期={date}")
        if account_id:
            scope.append(f"账号=@{account_id}")
        scope_text = "、".join(scope) if scope else "全部链接"

        n = len(self._rows)
        if n == 0:
            self.toast("当前筛选条件下没有链接，无需清空", title="提示", level="info")
            return

        if not self._clear_armed:
            # 第一次点击：按钮变红进入确认态，3 秒无操作自动复原
            self._clear_armed = True
            try:
                self._clear_btn.configure(
                    text=f"确认清空{n}条?", fg_color=COLORS["danger"],
                    hover_color=COLORS["danger_hover"], width=130)
            except Exception:  # noqa: BLE001
                pass
            self.toast(f"再点一次「确认清空」即删除 {scope_text}（{n} 条），不可恢复",
                       title="请确认", level="warning", duration=3200)
            self.after(3000, self._disarm_clear)
            return

        self._disarm_clear()
        try:
            deleted = self.ctx.result_service.clear_videos(
                account_id=account_id, publish_date=date)
        except Exception as exc:  # noqa: BLE001
            self.show_error_dialog("清空失败", str(exc), "详细错误已写入日志。")
            return
        self.toast(f"已清空 {deleted} 条链接（{scope_text}）",
                   title="清空完成", level="success")
        self._query()

    def _disarm_clear(self) -> None:
        """退出「确认清空」态，恢复按钮原样。"""
        self._clear_armed = False
        try:
            self._clear_btn.configure(text="清空链接", fg_color=COLORS["danger"],
                                      hover_color=COLORS["danger_hover"], width=92)
        except Exception:  # noqa: BLE001
            pass
