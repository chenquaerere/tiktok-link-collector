"""账号管理页面：搜索 / 地区分类 / 筛选 / 批量导入 / 启停 / 删除 / 编辑数量。"""
from __future__ import annotations

import csv
import os
import threading
from tkinter import filedialog

import customtkinter as ctk

from app.core import regions as region_util
from app.core.models import Account
from app.core.regions import REGION_FILTER_ALL, REGION_NONE

from ..theme import COLORS, FONT
from ..widgets import ScrollableTable, status_zh
from ..components import EmptyState, PageHeader
from .base_page import BasePage

# 昵称为空时的占位（避免首列空白看不出是「没取到」还是「忘了取」）
NICKNAME_PLACEHOLDER = "—"


class AccountsPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._nick_running = False          # 昵称刷新任务运行中（防重复点击）
        self._build()

    def _build(self) -> None:
        self.header = PageHeader(self, "账号管理", "管理你的 TikTok 账号池，支持按地区分类")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))

        # 顶部：搜索 + 地区筛选 + 状态筛选 + 批量导入
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=24)
        bar.grid_columnconfigure(1, weight=1)

        # 注意：CTkEntry 绑定 textvariable 后 placeholder 会被空值覆盖而不显示，
        # 因此这里不绑变量，改为 KeyRelease 直读。
        self.search = ctk.CTkEntry(bar, placeholder_text="搜索账号 / 备注…",
                                   font=FONT["body"], height=38)
        self.search.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.search.bind("<KeyRelease>", lambda e: self._render())

        self.region_filter = ctk.CTkComboBox(
            bar, values=[REGION_FILTER_ALL], width=126,
            font=FONT["body"], command=lambda _: self._render())
        self.region_filter.set(REGION_FILTER_ALL)
        self.region_filter.grid(row=0, column=2, padx=4)

        self.status_filter = ctk.CTkComboBox(
            bar, values=["全部状态", "仅启用", "仅禁用"], width=110,
            font=FONT["body"], command=lambda _: self._render())
        self.status_filter.set("全部状态")
        self.status_filter.grid(row=0, column=3, padx=4)

        ctk.CTkButton(bar, text="批量导入", width=100, height=38,
                      fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                      command=self._import_dialog).grid(row=0, column=4, padx=4)

        # 添加行：链接/用户名 + 归属地区 + 添加
        addbar = ctk.CTkFrame(self, fg_color="transparent")
        addbar.grid(row=2, column=0, sticky="ew", padx=24, pady=(8, 8))
        addbar.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(addbar, placeholder_text="输入主页链接或 @用户名，回车添加",
                                  font=FONT["body"], height=38)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self._add())
        self.add_region = ctk.CTkComboBox(addbar, values=[REGION_NONE], width=116,
                                          font=FONT["body"])
        self.add_region.set(REGION_NONE)
        self.add_region.grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(addbar, text="添加", width=80, height=38,
                      command=self._add).grid(row=0, column=2)

        # 操作行
        ops = ctk.CTkFrame(self, fg_color="transparent")
        ops.grid(row=3, column=0, sticky="ew", padx=24, pady=(6, 8))
        self._selected_lbl = ctk.CTkLabel(ops, text="已选 0 项", font=FONT["secondary"],
                                          text_color=COLORS["text_dim"])
        self._selected_lbl.grid(row=0, column=0, sticky="w")
        self._total_lbl = ctk.CTkLabel(ops, text="", font=FONT["secondary"],
                                       text_color=COLORS["text_faint"])
        self._total_lbl.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self._region_lbl = ctk.CTkLabel(ops, text="", font=FONT["secondary"],
                                        text_color=COLORS["text_faint"])
        self._region_lbl.grid(row=0, column=2, sticky="w", padx=(12, 0))
        ctk.CTkButton(ops, text="全选", width=62, height=32, fg_color=COLORS["surface_alt"],
                      command=lambda: self._select_toggle(True)).grid(row=0, column=3, padx=2)
        ctk.CTkButton(ops, text="反选", width=62, height=32, fg_color=COLORS["surface_alt"],
                      command=self._invert).grid(row=0, column=4, padx=2)
        ctk.CTkButton(ops, text="设置地区", width=84, height=32, fg_color=COLORS["primary"],
                      hover_color=COLORS["primary_hover"],
                      command=self._set_region).grid(row=0, column=5, padx=2)
        self._nick_btn = ctk.CTkButton(
            ops, text="刷新昵称", width=84, height=32, fg_color=COLORS["info"],
            hover_color=COLORS["info_hover"], command=self._refresh_nicknames)
        self._nick_btn.grid(row=0, column=6, padx=2)
        ctk.CTkButton(ops, text="启用", width=62, height=32, fg_color=COLORS["success"],
                      hover_color=COLORS["success_hover"],
                      command=lambda: self._set_enabled(True)).grid(row=0, column=7, padx=2)
        ctk.CTkButton(ops, text="禁用", width=62, height=32, fg_color=COLORS["warning"],
                      hover_color=COLORS["warning_hover"],
                      command=lambda: self._set_enabled(False)).grid(row=0, column=8, padx=2)
        ctk.CTkButton(ops, text="编辑数量", width=84, height=32, fg_color=COLORS["surface_alt"],
                      command=self._edit_count).grid(row=0, column=9, padx=2)
        ctk.CTkButton(ops, text="删除", width=62, height=32, fg_color=COLORS["danger"],
                      hover_color=COLORS["danger_hover"], command=self._delete).grid(
            row=0, column=10, padx=2)

        # 表格（昵称在最前：日常靠昵称认账号；其后是账号、地区）
        self.table = ScrollableTable(
            self,
            columns=["nickname", "username", "region", "profile_url", "collect_count",
                     "login_status", "last_collect_time", "enabled", "remark"],
            headers=["昵称", "账号", "地区", "主页", "采集数量", "登录状态",
                     "最后采集", "状态", "备注"],
            height=16,
            stretch_cols={"profile_url", "remark"},
            on_select=lambda sel: self._selected_lbl.configure(text=f"已选 {len(sel)} 项"),
        )
        self.table.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 20))
        self.table.set_widths({"nickname": 152, "username": 142, "region": 92,
                               "collect_count": 84, "login_status": 88,
                               "last_collect_time": 132, "enabled": 68})
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
        self.region_filter.set(REGION_FILTER_ALL)
        self._render()

    def _region_values(self):
        """地区下拉选项（预置地区 ∪ 库中出现过的自定义地区）。"""
        return self.ctx.account_service.region_options()

    @staticmethod
    def _region_sort_key(row):
        """排序键：让同地区账号聚集（视觉上就是分类）。

        顺序 = 预置地区顺序 → 自定义地区（按名称）→ 未分类放最后；
        同地区内保持录入顺序（id）。元组首项不同时不会比较后续元素，
        因此 int 与 str 混用是安全的。
        """
        name = (row["region"] or "").strip()
        rid = row["id"]
        if not name:
            return (2, 0, rid)
        if name in region_util.REGIONS:
            return (0, region_util.REGIONS.index(name), rid)
        return (1, name, rid)

    def _refresh_region_widgets(self, rows) -> None:
        """同步地区筛选下拉与地区统计文案（含自定义地区）。"""
        used = [r["region"] for r in rows if (r["region"] or "").strip()]
        opts = region_util.region_options(used)

        values = [REGION_FILTER_ALL] + opts + [REGION_NONE]
        cur = self.region_filter.get()
        self.region_filter.configure(values=values)
        if cur not in values:
            self.region_filter.set(REGION_FILTER_ALL)

        add_vals = opts + [REGION_NONE]
        cur_add = self.add_region.get()
        self.add_region.configure(values=add_vals)
        if cur_add not in add_vals:
            self.add_region.set(REGION_NONE)

        stats = [(n, c) for n, c in self.ctx.account_service.region_stats() if c]
        parts = [f"{name}{n}" for name, n in stats[:5]]
        text = " ".join(parts)
        if len(stats) > 5:
            text += " …"
        self._region_lbl.configure(text=text)

    def _render(self) -> None:
        rows = self.ctx.account_service.list()
        q = self.search.get().strip().lower()
        rf = self.region_filter.get()
        f = self.status_filter.get()
        filtered = []
        for r in rows:
            if q:
                hay = (f"{r['username']} {r['remark'] or ''} {r['profile_url']} "
                       f"{r['region'] or ''}").lower()
                if q not in hay:
                    continue
            if rf != REGION_FILTER_ALL and region_util.region_display(r["region"]) != rf:
                continue
            if f == "仅启用" and not r["enabled"]:
                continue
            if f == "仅禁用" and r["enabled"]:
                continue
            filtered.append(r)
        filtered.sort(key=self._region_sort_key)

        self.table.clear()
        for r in filtered:
            nickname = (r["display_name"] or "").strip() or NICKNAME_PLACEHOLDER
            self.table.insert_status(r["account_id"], (
                nickname, f"@{r['username']}",
                region_util.region_display(r["region"]),
                r["profile_url"], r["collect_count"],
                status_zh(r["login_status"]), r["last_collect_time"] or "",
                "启用" if r["enabled"] else "禁用", r["remark"] or "",
            ), "enabled" if r["enabled"] else "disabled")
        missing_nick = sum(1 for r in rows if not (r["display_name"] or "").strip())
        total_text = f"共 {len(rows)} 个账号 · 显示 {len(filtered)}"
        if missing_nick:
            total_text += f" · 昵称待获取 {missing_nick}"
        self._total_lbl.configure(text=total_text)
        self._refresh_region_widgets(rows)
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
        region = self.add_region.get()
        ok, msg = self.ctx.account_service.add(raw, region=region)
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

    # ---- 昵称 ----
    def _refresh_nicknames(self) -> None:
        """抓取 TikTok 昵称（有选中则只处理选中的，否则处理全部）。

        昵称来自主页首屏的 `item_list`（`author.nickname`），需要启动浏览器，
        因此放到后台线程执行；界面更新一律通过 ui_call 回到主线程。
        """
        if self._nick_running:
            self.toast("昵称正在获取中，请稍候", title="请稍候", level="warning")
            return
        sel = self.table.selected_iids()
        targets = list(sel) if sel else [r["account_id"]
                                         for r in self.ctx.account_service.list()]
        if not targets:
            self.toast("账号池为空，无可获取的昵称", title="提示", level="warning")
            return
        self._nick_running = True
        self._nick_btn.configure(state="disabled", text="获取中…")
        scope = f"选中的 {len(targets)} 个" if sel else f"全部 {len(targets)} 个"
        self.toast(f"开始获取{scope}账号的昵称，请勿关闭程序",
                   title="已开始", level="info", duration=5000)
        self.set_status(f"正在获取昵称（0/{len(targets)}）…")
        threading.Thread(target=self._nickname_worker, args=(targets,),
                         daemon=True).start()

    def _nickname_worker(self, account_ids) -> None:
        """后台线程：逐个账号取昵称并写库（单账号失败不阻断整体）。"""
        try:
            collector = self.ctx.build_collector()
        except Exception as exc:  # noqa: BLE001
            self.ui_call(self._on_nicknames_done, 0, len(account_ids),
                         f"{type(exc).__name__}: {exc}")
            return

        ok = 0
        fail = 0
        last_err = ""
        total = len(account_ids)
        for i, aid in enumerate(account_ids, start=1):
            row = self.ctx.account_service.get(aid)
            if not row:
                fail += 1
                continue
            acc = Account(account_id=row["account_id"], username=row["username"],
                          profile_url=row["profile_url"])
            self.ui_call(self.set_status,
                         f"正在获取昵称（{i - 1}/{total}）：@{row['username']}")
            try:
                nickname = collector.fetch_nickname(acc)
            except Exception as exc:  # noqa: BLE001
                nickname, last_err = "", f"{type(exc).__name__}: {exc}"
            if nickname:
                self.ctx.db.set_account_display_name(aid, nickname)
                ok += 1
            else:
                fail += 1
        self.ui_call(self._on_nicknames_done, ok, fail, last_err)

    def _on_nicknames_done(self, ok: int, fail: int, err: str = "") -> None:
        self._nick_running = False
        self._nick_btn.configure(state="normal", text="刷新昵称")
        self._render()
        if ok:
            extra = f"，{fail} 个未取到" if fail else ""
            self.toast(f"已获取 {ok} 个账号的昵称{extra}", title="完成", level="success")
        else:
            detail = f"：{err[:80]}" if err else "（请确认登录态有效，且账号有公开作品）"
            self.toast(detail, title=f"{fail} 个账号未取到昵称",
                       level="error", duration=7000)
            self.show_error_dialog(
                "未能获取昵称",
                "可能是登录态失效、账号无作品，或触发了 TikTok 风控。",
                "建议：先在「采集任务」确认该账号能正常采集，再回来刷新昵称。")
        self.set_status("昵称获取结束")

    # ---- 地区分类 ----
    def _set_region(self) -> None:
        """为选中账号批量设置地区（下拉可选，也支持直接输入新的地区名）。"""
        sel = self.table.selected_iids()
        if not sel:
            self.toast("请先在表格里选中账号，再点「设置地区」",
                       title="未选择账号", level="warning")
            return
        opts = self._region_values()

        win = ctk.CTkToplevel(self)
        win.title("设置地区")
        win.geometry("430x250")
        win.configure(fg_color=COLORS["surface"])
        win.transient(self.window if self.window else self)
        # 先让窗口完成映射再置顶/抢焦点：不用 after 延迟回调，
        # 否则弹窗被快速关闭时 Tk 会执行到已销毁的命令（invalid command name 噪声）
        win.update_idletasks()
        win.lift()
        try:
            win.grab_set()
        except Exception:  # noqa: BLE001  窗口未 viewable 时 grab 会抛错，不影响使用
            pass
        win.focus_force()

        ctk.CTkLabel(win, text=f"为选中的 {len(sel)} 个账号设置地区",
                     font=FONT["body_strong"], text_color=COLORS["text"]).pack(pady=(20, 10))
        combo = ctk.CTkComboBox(win, values=opts + [REGION_NONE], width=250,
                                font=FONT["body"])
        combo.pack()
        combo.set(REGION_NONE)
        ctk.CTkLabel(win, text="可从下拉选择，也可直接输入新的地区名",
                     font=FONT["caption"], text_color=COLORS["text_faint"]).pack(pady=(6, 14))

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack()

        def apply() -> None:
            value = combo.get().strip()
            win.destroy()
            n = self.ctx.account_service.set_regions(sel, value)
            if region_util.normalize_region(value):
                title, msg = "设置成功", f"已将 {n} 个账号归类到「{value}」"
            else:
                title, msg = "已取消分类", f"已取消 {n} 个账号的地区分类"
            self.toast(msg, title=title, level="success")
            self._render()

        ctk.CTkButton(btns, text="确定", width=96, font=FONT["button"],
                      fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
                      command=apply).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="取消", width=76, font=FONT["button"],
                      fg_color=COLORS["surface_alt"],
                      command=win.destroy).pack(side="left", padx=6)

    # ---- 批量导入 ----
    def _import_dialog(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("批量导入账号")
        win.geometry("620x560")
        win.configure(fg_color=COLORS["surface"])
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="每行一个主页链接或 @用户名", font=FONT["secondary"],
                     text_color=COLORS["text_dim"], anchor="w").pack(
            anchor="w", padx=20, pady=(18, 6))

        # 导入到指定地区（可选）
        rrow = ctk.CTkFrame(win, fg_color="transparent")
        rrow.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(rrow, text="导入到地区：", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).pack(side="left")
        region_combo = ctk.CTkComboBox(rrow, values=[REGION_NONE] + self._region_values(),
                                       width=160, font=FONT["body"])
        region_combo.pack(side="left", padx=6)
        region_combo.set(REGION_NONE)
        ctk.CTkLabel(rrow, text="（可留「未分类」，导入后再批量归类）",
                     font=FONT["caption"], text_color=COLORS["text_faint"]).pack(
            side="left", padx=4)

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
            result = self.ctx.account_service.import_many(
                lines, region=region_combo.get().strip())
            imported = len(result["imported"])
            failed = result["failed"]
            skipped = len(result["skipped"])
            region_tag = region_util.normalize_region(region_combo.get())
            win.destroy()
            self._render()
            where = f"到「{region_tag}」" if region_tag else ""
            if failed:
                detail = "；".join(f"{f['input'][:30]}：{f['error']}" for f in failed[:5])
                self.toast(f"成功 {imported} / 跳过 {skipped} / 失败 {len(failed)}",
                           title="导入完成", level="warning", duration=6000)
                self.toast(detail, title="失败详情", level="error", duration=6000)
            else:
                self.toast(f"成功导入 {imported} 个{where}，跳过重复 {skipped} 个",
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
