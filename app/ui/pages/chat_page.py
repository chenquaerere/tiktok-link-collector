"""聊天链接采集页面 —— 左右分栏布局（v1.2 重构）。

左列（主区）：账号/登录 + 会话列表（实时过滤 + 类型筛选，点选即选定）
右列：最近使用 + 目标确认 + 采集控制 + 进度 + 链接结果

设计原则：
- 会话列表占页面主要高度（不再被多层卡片挤压）。
- 免关键词：直接浏览消息列表，顶部过滤框输入即过滤（无网络请求）。
- emoji 用彩色图片渲染（tkinter 不支持彩色 emoji，见 app/ui/emoji.py）。
- 与作品采集页完全独立，不复用其采集引擎。
"""
from __future__ import annotations

import queue
import threading
from typing import List, Optional

import customtkinter as ctk

from app.chat.models import (
    CHAT_TYPE_FRIEND,
    CHAT_TYPE_GROUP,
    ChatCandidate,
    ChatTarget,
)
from app.collector.exceptions import LoginRequired
from .. import emoji as emoji_util

from ..theme import COLORS, FONT
from ..components import PageHeader
from ..notify import notify_success, notify_failure
from .base_page import BasePage


def _norm(s: str) -> str:
    return (s or "").strip().lower().lstrip("@")


class ChatPage(BasePage):
    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._login_running = False
        self._convs_loading = False               # 会话列表加载中（防呆）
        self._convs: List[ChatCandidate] = []      # 消息页会话列表（好友+群聊）
        self._result_var = ctk.StringVar(value="")  # 单选绑定
        self._img_refs: List[object] = []          # 防 CTkImage 被垃圾回收
        self._row_frames: dict = {}                # stable_key -> 行容器（选中高亮）
        self._selected: Optional[ChatTarget] = None
        self._links: List[str] = []                # 本次采集的链接
        # ⚠️ 跨线程回传一律走队列：tkinter 的 after() 不是线程安全的，
        #    在 worker 线程里直接 after() 会抛
        #    RuntimeError: main thread is not in main loop
        #    （表现为「点了没反应」、界面永不更新且无任何报错）。
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._pump_id = None
        self._stop_event = threading.Event()       # 真实停止信号（传给采集器）
        self._account_active = ""                  # 实际在用的账号（下拉回退用）
        self._counting_up = False                  # 采集数量输入框的写入标记
        try:
            from app.log.logger import get_logger
            self._log = get_logger("ui.chat")
        except Exception:  # noqa: BLE001
            self._log = None
        try:
            emoji_util.set_cache_dir(str(self.ctx.base_dir / "data" / "emoji_cache"))
        except Exception:  # noqa: BLE001
            pass
        self._build()

    def _logi(self, msg: str, *args) -> None:
        """UI 动作日志：用户反馈「点了没反应」时靠它定位卡在哪一步。"""
        if self._log is not None:
            try:
                self._log.info(msg, *args)
            except Exception:  # noqa: BLE001
                pass

    # ---------------- UI ----------------
    def _build(self) -> None:
        self.header = PageHeader(self, "聊天链接采集",
                                 "选账号 → 登录账号 → 加载会话列表 → 点选目标 → 采集最新 N 条视频链接")
        self.header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 16))
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=11)   # 左列（会话列表）更宽
        main.grid_columnconfigure(1, weight=9)    # 右列（操作区）
        main.grid_rowconfigure(0, weight=1)

        # ================= 左列：会话列表 =================
        left = ctk.CTkFrame(main, fg_color=COLORS["surface"], corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_rowconfigure(3, weight=1)       # 列表区吃掉全部剩余高度
        left.grid_columnconfigure(0, weight=1)

        # -- 工具行：账号 + 登录 + 刷新 --
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 2))
        ctk.CTkLabel(tools, text="采集账号", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=0, padx=(4, 6))
        self._account_menu = ctk.CTkOptionMenu(tools, width=170, font=FONT["body"],
                                               values=["（无账号）"],
                                               command=lambda _v: self._on_account_changed())
        self._account_menu.grid(row=0, column=1, padx=(0, 8))
        self._login_btn = ctk.CTkButton(tools, text="登录账号", width=104, height=30,
                                        fg_color=COLORS["warning"],
                                        hover_color=COLORS["warning_hover"],
                                        text_color="#141824",
                                        command=self._do_login)
        self._login_btn.grid(row=0, column=2, padx=4)
        self._conv_btn = ctk.CTkButton(tools, text="刷新会话列表", width=110, height=30,
                                       fg_color=COLORS["primary"],
                                       command=self._load_convos)
        self._conv_btn.grid(row=0, column=3, padx=(4, 4))

        # -- 登录状态 --
        self._login_hint = ctk.CTkLabel(left, text="首次使用请先点「登录账号」：弹出浏览器登录一次，之后免登录",
                                        font=FONT["caption"], text_color=COLORS["warning"],
                                        anchor="w")
        self._login_hint.grid(row=1, column=0, sticky="w", padx=16, pady=(2, 6))

        # -- 过滤行：实时过滤 + 类型筛选 --
        filt = ctk.CTkFrame(left, fg_color="transparent")
        filt.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 6))
        filt.grid_columnconfigure(0, weight=1)
        self._filter_var = ctk.StringVar()
        self._filter_var.trace_add("write", lambda *a: self._refresh_results())
        self._filter_entry = ctk.CTkEntry(filt, font=FONT["body"],
                                          textvariable=self._filter_var,
                                          placeholder_text="输入关键词实时过滤（名称 / @用户名 / 消息摘要）")
        self._filter_entry.grid(row=0, column=0, sticky="ew", padx=(4, 8))
        self._type_seg = ctk.CTkSegmentedButton(
            filt, values=["全部", "好友", "群聊"], font=FONT["body"],
            command=lambda v: self._refresh_results())
        self._type_seg.set("全部")
        self._type_seg.grid(row=0, column=1, padx=(0, 4))

        # -- 会话列表（主区） --
        self._conv_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._conv_scroll.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 2))

        # -- 计数 --
        self._count_hint = ctk.CTkLabel(left, text="尚未加载，点右上角「刷新会话列表」",
                                        font=FONT["caption"], text_color=COLORS["text_faint"],
                                        anchor="w")
        self._count_hint.grid(row=4, column=0, sticky="w", padx=16, pady=(2, 10))

        # ================= 右列：操作区 =================
        right = ctk.CTkFrame(main, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_rowconfigure(3, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # -- 最近使用（横排） --
        recent = ctk.CTkFrame(right, fg_color=COLORS["surface"], corner_radius=12)
        recent.grid(row=0, column=0, sticky="ew")
        recent.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(recent, text="最近使用", font=FONT["caption"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=0,
                                                         padx=(12, 6), pady=8)
        self._recent_box = ctk.CTkFrame(recent, fg_color="transparent")
        self._recent_box.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=6)

        # -- 目标确认 + 采集控制 --
        sel = ctk.CTkFrame(right, fg_color=COLORS["surface"], corner_radius=12)
        sel.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        sel.grid_columnconfigure(0, weight=1)
        self._selected_lbl = ctk.CTkLabel(sel, text="未选择目标（在左侧列表点选）",
                                          font=FONT["body_strong"],
                                          text_color=COLORS["text_dim"], anchor="w")
        self._selected_lbl.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        act = ctk.CTkFrame(sel, fg_color="transparent")
        act.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 12))
        ctk.CTkLabel(act, text="采集数量", font=FONT["secondary"],
                     text_color=COLORS["text_dim"]).grid(row=0, column=0, padx=(0, 6))
        self._count_entry = ctk.CTkEntry(act, width=64, font=FONT["body"])
        self._count_entry.grid(row=0, column=1)
        self._start_btn = ctk.CTkButton(act, text="开始采集", width=110, height=34,
                                        fg_color=COLORS["primary"], command=self._start)
        self._start_btn.grid(row=0, column=2, padx=(14, 4))
        self._stop_btn = ctk.CTkButton(act, text="停止", width=76, height=34,
                                       fg_color=COLORS["danger"],
                                       hover_color=COLORS["danger_hover"],
                                       state="disabled", command=self._stop)
        self._stop_btn.grid(row=0, column=3, padx=(4, 0))

        # -- 进度 --
        prog = ctk.CTkFrame(right, fg_color=COLORS["surface"], corner_radius=12)
        prog.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        prog.grid_columnconfigure(0, weight=1)
        self._progress = ctk.CTkProgressBar(prog, height=10)
        self._progress.set(0)
        self._progress.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        self._status_lbl = ctk.CTkLabel(prog, text="等待开始", font=FONT["body"],
                                        text_color=COLORS["text_dim"], anchor="w")
        self._status_lbl.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 12))
        # 可视化开关：勾选后浏览器可见，可亲眼看到程序进入所选对话框
        self._show_browser_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            prog, text="显示浏览器窗口", font=FONT["caption"],
            text_color=COLORS["text_dim"], variable=self._show_browser_var,
            checkbox_width=16, checkbox_height=16, border_width=1,
        ).grid(row=1, column=1, sticky="e", padx=(0, 14), pady=(0, 12))

        # -- 链接结果 --
        out = ctk.CTkFrame(right, fg_color=COLORS["surface"], corner_radius=12)
        out.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        out.grid_rowconfigure(1, weight=1)
        out.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(out, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text="采集到的链接", font=FONT["section"],
                     text_color=COLORS["text"], anchor="w").grid(row=0, column=0)
        self._clear_links_btn = ctk.CTkButton(
            bar, text="清空", width=56, height=28,
            fg_color=COLORS["surface_alt"], hover_color=COLORS["danger"],
            text_color=COLORS["text_dim"], command=self._clear_links)
        self._clear_links_btn.grid(row=0, column=1, padx=(0, 6))
        self._export_btn = ctk.CTkButton(
            bar, text="导出", width=56, height=28,
            fg_color=COLORS["surface_alt"], hover_color=COLORS["border"],
            text_color=COLORS["text_dim"], command=self._export_links)
        self._export_btn.grid(row=0, column=2, padx=(0, 6))
        self._copy_btn = ctk.CTkButton(bar, text="复制全部", width=88, height=28,
                                       fg_color=COLORS["accent"], text_color="#141824",
                                       hover_color=COLORS["accent_hover"],
                                       command=self._copy_links)
        self._copy_btn.grid(row=0, column=3)
        self._links_box = ctk.CTkTextbox(out, font=FONT["body"], wrap="none")
        self._links_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(6, 12))

        # 启动主线程轮询：worker 线程只往队列里塞事件，界面更新全在主线程做
        self._count_entry.insert(0, str(self._load_last_count()))
        self._schedule_pump()

    # ---------------- 线程安全的事件泵 ----------------
    def _schedule_pump(self) -> None:
        try:
            self._pump_id = self.after(120, self._pump)
        except Exception:  # noqa: BLE001
            self._pump_id = None

    def _pump(self) -> None:
        """主线程定时器：把 worker 线程投递的事件在 UI 线程里派发。"""
        try:
            if not self.winfo_exists():
                return
        except Exception:  # noqa: BLE001
            return
        while True:
            try:
                kind, payload = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                self._dispatch(kind, payload)
            except Exception as exc:  # noqa: BLE001
                self._logi("事件处理异常 %s: %s: %s", kind, type(exc).__name__, exc)
        self._schedule_pump()

    def _dispatch(self, kind: str, payload) -> None:
        if kind == "stage":
            self._set_status(str(payload), COLORS["accent"])
        elif kind == "login_hint":
            text, color = payload
            self._login_hint.configure(text=text, text_color=color)
        elif kind == "login_done":
            ok, err = payload
            self._on_login_done(ok, err)
        elif kind == "convos_done":
            self._on_convos_done(payload)
        elif kind == "convos_error":
            self._on_convos_error(str(payload))
        elif kind == "collect_progress":
            self._set_status(str(payload), COLORS["text_dim"])
        elif kind == "collect_ratio":
            try:
                self._progress.set(max(0.0, min(1.0, float(payload))))
            except Exception:  # noqa: BLE001
                pass
        elif kind == "collect_done":
            self._on_collect_done(payload)
        elif kind == "collect_error":
            err, login = payload
            self._on_collect_error(str(err), bool(login))
        else:
            self._logi("未知事件: %s", kind)

    # ---------------- 数据 ----------------
    def refresh(self) -> None:
        rows = self.ctx.account_service.list(enabled_only=True)
        names = [f"@{r['username']}" for r in rows] or ["（无账号）"]
        self._account_menu.configure(values=names)
        if rows:
            self._account_menu.set(names[0])
        self._account_active = self._account_menu.get() or ""
        self._load_recent()

    def on_leave(self) -> None:
        # 离开页面时把占位文案复位，避免回收站式残留
        pass

    def _on_account_changed(self) -> None:
        """切换账号必须清空已选目标与会话列表。

        ⚠️ 否则会用 A 账号的 conversation_id 去 B 账号的会话列表里点选，
        结果是「采不到」或采到别的会话（v6 之前就踩过目标串号的坑）。
        """
        now = self._account_menu.get() or ""
        if self._running or self._convs_loading:
            # 任务进行中不允许换账号：把下拉框回退到实际在用的账号，
            # 避免「显示 B 账号、实际用 A 账号的目标」的不一致。
            try:
                self._account_menu.set(self._account_active or now)
            except Exception:  # noqa: BLE001
                pass
            self.toast("任务进行中，账号将在结束后才能切换",
                       title="请稍候", level="warning")
            return
        self._account_active = now
        self._selected = None
        self._convs = []
        self._result_var.set("")
        self._row_frames.clear()
        self._selected_lbl.configure(text="未选择目标（在左侧列表点选）",
                                     text_color=COLORS["text_dim"])
        self._count_hint.configure(text="尚未加载，点右上角「刷新会话列表」")
        self._refresh_results()
        self._set_status("已切换账号，请重新点「刷新会话列表」加载该账号的会话",
                         COLORS["text_dim"])
        self._logi("切换采集账号: %s", now)

    def _service(self):
        """构建聊天服务，并把「显示浏览器窗口」开关传进去。"""
        svc = self.ctx.build_chat_service()
        try:
            svc.show_browser = bool(self._show_browser_var.get())
        except Exception:  # noqa: BLE001
            pass
        return svc

    def _current_account(self):
        name = (self._account_menu.get() or "").lstrip("@").strip()
        if not name or name == "（无账号）":
            return None
        row = self.ctx.db.get_account(name)
        if row:
            from app.core.models import Account
            return Account(account_id=row["account_id"], username=row["username"],
                           profile_url=row["profile_url"])
        return None

    # ---------------- 会话列表 ----------------
    def _load_convos(self) -> None:
        if self._login_running or self._convs_loading:
            return
        account = self._current_account()
        if not account:
            self.toast("请先在「账号管理」添加账号", title="提示", level="warning")
            return
        self._convs_loading = True
        self._conv_btn.configure(state="disabled")
        self._set_status("正在从消息页拉取会话列表…（约需 15~40 秒，请勿重复点击）",
                         COLORS["accent"])
        self._thread = threading.Thread(target=self._convos_worker,
                                        args=(account,), daemon=True)
        self._thread.start()

    def _convos_worker(self, account) -> None:
        def on_stage(msg: str) -> None:
            self._q.put(("stage", f"加载会话列表：{msg}"))
        try:
            data = self._service().list_all_targets(account,
                                                                  on_stage=on_stage)
            self._q.put(("convos_done", data))
        except LoginRequired as exc:
            self._q.put(("convos_error", str(exc)))
        except Exception as exc:  # noqa: BLE001
            self._q.put(("convos_error", str(exc)))

    def _on_convos_done(self, data: dict) -> None:
        self._convs_loading = False
        self._conv_btn.configure(state="normal")
        convs = data.get("conversations", [])
        self._convs = convs
        n_friend = sum(1 for c in convs if c.chat_type == CHAT_TYPE_FRIEND)
        n_group = len(convs) - n_friend
        self._count_hint.configure(
            text=f"好友 {n_friend} · 群聊 {n_group} · 共 {len(convs)} 条，点选即选定")
        self._set_status(f"已加载会话列表：好友 {n_friend} · 群聊 {n_group}", COLORS["success"])
        self._refresh_results()

    def _on_convos_error(self, err: str) -> None:
        self._convs_loading = False
        self._conv_btn.configure(state="normal")
        if "login" in err.lower() or "登录" in err or "log in" in err.lower():
            self._set_status("需要登录消息功能", COLORS["warning"])
            self.show_error_dialog(
                "需要登录消息功能", err,
                "点击左上角「登录账号」按钮，在弹出的浏览器里登录一次即可\n"
                "（登录态按账号保存，之后不用再登）。")
        else:
            self._set_status(f"会话列表获取失败：{err[:60]}", COLORS["danger"])
            self.show_error_dialog("会话列表获取失败", err, "请检查网络/代理后重试；详细错误见日志。")

    def _filtered_convs(self) -> List[ChatCandidate]:
        q = _norm(self._filter_var.get())
        t = self._type_seg.get()
        out = []
        for c in self._convs:
            if t == "好友" and c.chat_type != CHAT_TYPE_FRIEND:
                continue
            if t == "群聊" and c.chat_type != CHAT_TYPE_GROUP:
                continue
            if q and q not in _norm(c.name) and q not in _norm(c.handle) \
                    and q not in _norm(c.subtitle):
                continue
            out.append(c)
        return out

    def _refresh_results(self) -> None:
        for w in self._conv_scroll.winfo_children():
            w.destroy()
        self._img_refs.clear()
        self._row_frames.clear()
        cands = self._filtered_convs()
        if not cands:
            tip = ("暂无会话数据\n点击右上角「刷新会话列表」加载"
                   if not self._convs else
                   "无匹配会话\n（清空过滤条件或切换类型后重试）")
            ctk.CTkLabel(self._conv_scroll, text=tip, font=FONT["body"],
                         text_color=COLORS["text_faint"], justify="center").pack(pady=40)
            return
        for c in cands:
            self._add_result_row(c)
        # 过滤/重渲染后保持已选目标的选中态
        if self._selected and self._selected.conversation_id:
            self._highlight_selected(f"conv:{self._selected.conversation_id}")

    # ---- 结果行渲染（整行可点击选中，含彩色 emoji） ----
    def _add_result_row(self, c: ChatCandidate) -> None:
        """一行 = 单选钮 + [彩色emoji图] + 名称 + 类型徽标 + 摘要。

        ⚠️ 整行可点（含名称/空白区）：旧版只有左侧那个小圆圈能点，
        用户点名称时没有任何反应 → 反馈「选了没反应」。
        """
        key = c.stable_key
        row = ctk.CTkFrame(self._conv_scroll, fg_color="transparent",
                           corner_radius=8, height=34)
        row.pack(fill="x", padx=4, pady=1)
        row.grid_columnconfigure(1, weight=1)

        rb = ctk.CTkRadioButton(row, text="", variable=self._result_var, value=key,
                                width=24, command=lambda cc=c: self._pick(cc))
        rb.grid(row=0, column=0, padx=(8, 4), pady=6)

        name_box = ctk.CTkFrame(row, fg_color="transparent")
        name_box.grid(row=0, column=1, sticky="w", pady=6)

        name = c.name or ""
        if emoji_util.contains_emoji(name):
            pos = 0
            for m in emoji_util._EMOJI_TOKEN_RE.finditer(name):
                if m.start() > pos:
                    self._add_text_seg(name_box, name[pos:m.start()])
                pil = emoji_util.render_emoji_image(m.group(0), 20)
                if pil is not None:
                    img = ctk.CTkImage(light_image=pil, dark_image=pil, size=pil.size)
                    lbl = ctk.CTkLabel(name_box, image=img, text="")
                    lbl.pack(side="left", padx=(0, 1))
                    self._img_refs.append(img)
                pos = m.end()
            if pos < len(name):
                self._add_text_seg(name_box, name[pos:])
        else:
            self._add_text_seg(name_box, name)

        badge = "群" if c.chat_type == CHAT_TYPE_GROUP else "友"
        badge_color = COLORS["warning"] if c.chat_type == CHAT_TYPE_GROUP else COLORS["accent"]
        ctk.CTkLabel(name_box, text=badge, font=FONT["caption"],
                     text_color=badge_color).pack(side="left", padx=(4, 0))
        sub = (f"@{c.handle}" if (c.chat_type == CHAT_TYPE_FRIEND and c.handle)
               else (c.subtitle[:40] if c.subtitle else ""))
        if sub:
            ctk.CTkLabel(name_box, text=sub, font=FONT["caption"],
                         text_color=COLORS["text_faint"]).pack(side="left", padx=(8, 0))

        self._row_frames[key] = row
        self._bind_row_click(row, c)

    def _bind_row_click(self, row, cand: ChatCandidate) -> None:
        """把整行（含所有子控件）绑上单击选中 / 双击直接采集。

        ⚠️ CTk 控件的 `bind()` 实际是绑到内部 canvas 上的（CTkBaseClass.bind
        转发到 self._canvas），而真实鼠标点击也落在 canvas 上；原生 tk 控件
        则绑自身。这里按「有无 _canvas」二选一，避免同一 canvas 被绑两次
        （add=True 会导致一次点击触发两次回调）。
        """
        def on_click(_e=None, cc=cand):
            self._pick(cc)
            return "break"

        def on_double(_e=None, cc=cand):
            self._pick(cc)
            self._start()
            return "break"

        targets = []
        for w in [row] + list(self._descendants(row)):
            inner = getattr(w, "_canvas", None)
            targets.append(inner if inner is not None else w)
        for w in targets:
            for seq, fn in (("<Button-1>", on_click), ("<Double-Button-1>", on_double)):
                try:
                    w.bind(seq, fn)
                except Exception:  # noqa: BLE001
                    pass
        for w in [row] + list(self._descendants(row)):
            try:
                w.configure(cursor="hand2")
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from ChatPage._descendants(child)

    def _add_text_seg(self, parent, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        ctk.CTkLabel(parent, text=text, font=FONT["body"],
                     text_color=COLORS["text"]).pack(side="left", padx=(0, 2))

    def _highlight_selected(self, key: str) -> None:
        for k, row in self._row_frames.items():
            try:
                row.configure(fg_color=(COLORS["primary_soft"] if k == key
                                        else "transparent"))
            except Exception:  # noqa: BLE001
                pass

    def _pick(self, cand: ChatCandidate) -> None:
        target = self._service().build_target(cand)
        self._selected = target
        self._result_var.set(cand.stable_key)
        self._highlight_selected(cand.stable_key)
        self._scroll_row_into_view(cand.stable_key)
        detail = f"  {target.detail_label}" if target.detail_label else ""
        self._selected_lbl.configure(
            text=f"✓ 已选择：{target.name}{detail}", text_color=COLORS["success"])
        self._set_status(f"已选定目标：{target.name}（{target.type_label}），点「开始采集」"
                         f"或双击该行直接采集", COLORS["accent"])
        self._logi("选中目标: type=%s name=%s cid=%s", cand.chat_type, cand.name,
                   cand.conversation_id)

    # ---------------- 消息功能一键登录 ----------------
    def _do_login(self) -> None:
        if self._login_running:
            return
        account = self._current_account()
        if not account:
            self.toast("请先在「账号管理」添加账号", title="提示", level="warning")
            return
        self._login_running = True
        self._login_btn.configure(state="disabled")
        self._conv_btn.configure(state="disabled")
        self._login_hint.configure(text="正在弹出浏览器…", text_color=COLORS["accent"])
        self._thread = threading.Thread(target=self._login_worker,
                                        args=(account,), daemon=True)
        self._thread.start()

    def _login_worker(self, account) -> None:
        def on_status(msg: str) -> None:
            self._q.put(("login_hint", (msg[:70], COLORS["text_dim"])))
        try:
            ok = self._service().open_messages_login(account,
                                                                   on_status=on_status)
            self._q.put(("login_done", (ok, "")))
        except Exception as exc:  # noqa: BLE001
            self._q.put(("login_done", (False, str(exc))))

    def _on_login_done(self, ok: bool, err: str = "") -> None:
        self._login_running = False
        self._login_btn.configure(state="normal")
        self._conv_btn.configure(state="normal")
        if ok:
            self._login_hint.configure(text="✓ 登录成功，已保存登录态",
                                       text_color=COLORS["success"])
            self.toast("登录成功，正在加载会话列表…", title="消息功能", level="success")
            self._load_convos()  # 登录成功自动拉会话列表
        else:
            self._login_hint.configure(
                text=(f"登录未完成：{err[:50]}" if err else "登录未完成（超时或取消了登录）"),
                text_color=COLORS["warning"])

    # ---------------- 最近使用 ----------------
    def _load_recent(self) -> None:
        for w in self._recent_box.winfo_children():
            w.destroy()
        try:
            recents = self._service().recent_targets()
        except Exception:  # noqa: BLE001
            recents = []
        if not recents:
            ctk.CTkLabel(self._recent_box, text="暂无", font=FONT["caption"],
                         text_color=COLORS["text_faint"]).pack(side="left")
            return
        for t in recents[:5]:
            label = f"{t.type_label}｜{t.name}"
            btn = ctk.CTkButton(self._recent_box, text=label, height=26,
                                font=FONT["caption"], anchor="w",
                                fg_color=COLORS["surface_alt"],
                                hover_color=COLORS["surface"],
                                text_color=COLORS["text_dim"],
                                command=lambda tt=t: self._use_recent(tt))
            btn.pack(side="left", padx=(0, 6))

    def _use_recent(self, target: ChatTarget) -> None:
        """点「最近使用」：选中该目标，并尽量在左侧列表里同步高亮对应行。"""
        self._selected = target
        detail = f"  {target.detail_label}" if target.detail_label else ""
        self._selected_lbl.configure(
            text=f"✓ 已选择（最近）：{target.name}{detail}", text_color=COLORS["success"])
        key = f"conv:{target.conversation_id}" if target.conversation_id else ""
        if key and key in self._row_frames:
            self._result_var.set(key)
            self._highlight_selected(key)
            self._scroll_row_into_view(key)
        self._logi("使用最近目标: %s cid=%s", target.name, target.conversation_id)

    def _scroll_row_into_view(self, key: str) -> None:
        """把选中的会话行滚动到可视区域（避免高亮了却在屏幕外）。"""
        row = self._row_frames.get(key)
        if row is None:
            return
        try:
            self._conv_scroll.update_idletasks()
            total = max(1, self._conv_scroll.winfo_children()[-1].winfo_y()
                        + self._conv_scroll.winfo_children()[-1].winfo_height())
            frac = max(0.0, min(1.0, row.winfo_y() / total))
            self._conv_scroll._parent_canvas.yview_moveto(max(0.0, frac - 0.1))
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 采集 ----------------
    def _start(self) -> None:
        if self._running:
            self._logi("忽略点击：已有采集任务在运行")
            return
        account = self._current_account()
        if not account:
            self.toast("请先选择采集账号", title="提示", level="warning")
            return
        if self._convs_loading:
            self._set_status("会话列表正在加载（约需 15~40 秒），加载完成后再选择目标",
                             COLORS["warning"])
            self.toast("会话列表正在加载，请等左侧列表出现后再点选目标",
                       title="请稍候", level="warning")
            return
        if not self._selected:
            self._set_status("还没选目标：在左侧列表点一下群聊/好友那一行即可选中",
                             COLORS["warning"])
            self.toast("请在左侧列表点选一个目标聊天（整行都可点，双击直接开始采集）",
                       title="未选择目标", level="warning", duration=5000)
            return
        try:
            count = max(1, int(self._count_entry.get().strip()))
        except ValueError:
            count = 15
        count = min(count, 200)                     # 上限保护，避免误填超大数字
        self._count_entry.delete(0, "end")
        self._count_entry.insert(0, str(count))
        self._save_last_count(count)
        target = self._selected
        if not target.conversation_id:
            self.toast("该目标缺少会话标识（未开过聊天），请先在 TikTok 里与对方开一次对话",
                       title="无法定位聊天", level="warning", duration=6000)
            return

        # 不再弹模态确认框：目标已在右侧「已选择」区明确展示，点击即开始。
        # （旧版这里弹 CTkToplevel 确认框，弹窗被主窗口遮住时会 grab 卡住主界面，
        #   用户看到的就是「点了没反应」，且日志里连一行采集记录都没有。）
        self._logi("点击开始采集: account=%s target=%s(%s) cid=%s count=%d",
                   account.username, target.name, target.chat_type,
                   target.conversation_id, count)
        self._running = True
        self._stop_event.clear()                    # 复位停止信号
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._progress.set(0.02)
        self._links_box.delete("1.0", "end")
        self._links = []
        self._set_status(
            f"已启动采集：{target.type_label}「{target.name}」最新 {count} 条链接，"
            f"正在打开会话…", COLORS["accent"])
        self.set_status("聊天采集中…")
        self._thread = threading.Thread(target=self._collect_worker,
                                        args=(account, target, count), daemon=True)
        self._thread.start()

    def _collect_worker(self, account, target, count) -> None:
        def on_progress(stage: str) -> None:
            self._q.put(("collect_progress", stage))

        def on_ratio(v: float) -> None:
            self._q.put(("collect_ratio", v))
        try:
            result = self._service().collect(account, target, count,
                                             on_progress=on_progress,
                                             stop_event=self._stop_event,
                                             on_ratio=on_ratio)
            self._q.put(("collect_done", result))
        except LoginRequired as exc:
            self._q.put(("collect_error", (str(exc), True)))
        except Exception as exc:  # noqa: BLE001
            self._q.put(("collect_error", (str(exc), False)))

    def _on_collect_done(self, result) -> None:
        self._running = False
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._links = [it.video_url for it in result.links]
        self._links_box.delete("1.0", "end")
        self._links_box.insert("1.0", "\n".join(self._links))
        try:
            self._links_box.see("1.0")      # 回到顶部，最新那条在最上面
        except Exception:  # noqa: BLE001
            pass
        n = len(self._links)
        if result.status == "completed":
            self._progress.set(1)
        elif result.status == "stopped":
            self._progress.set(min(0.95, max(0.05, n / max(1, result.requested_count))))
        else:
            self._progress.set(0.7 if n else 0)
        color = COLORS["success"]
        label = "完成"
        if result.status == "failed":
            color, label = COLORS["danger"], "失败"
        elif result.status == "stopped":
            color, label = COLORS["warning"], "已停止"
        elif result.status != "completed":
            color, label = COLORS["warning"], result.status
        authors = {u.split("/@")[1].split("/")[0] for u in self._links if "/@" in u}
        self._set_status(
            f"{label}：采到 {n}/{result.requested_count} 条链接"
            f"（{len(authors)} 个作者）"
            + (f"｜{result.error}" if result.error else ""), color)
        self.set_status("聊天采集结束")
        self._logi("采集完成: target=%s status=%s links=%d authors=%d error=%s",
                   result.target.name if result.target else "-",
                   result.status, n, len(authors), result.error or "-")
        if result.status != "stopped" and self.ctx.config.get("notify_sound", True):
            (notify_success if result.status == "completed" else notify_failure)()
        if result.status == "failed":
            self.show_error_dialog("采集失败", result.error, "请确认目标聊天仍存在后重试。")
        self._load_recent()

    # ---------------- 清空链接 ----------------
    def _clear_links(self) -> None:
        """清空右侧链接框 + 该目标已存的链接（内联执行，不弹模态框）。"""
        n = len(self._links)
        self._links = []
        try:
            self._links_box.delete("1.0", "end")
        except Exception:  # noqa: BLE001
            pass
        target = self._selected
        if target is not None and target.conversation_id:
            try:
                from app.chat.store import target_stable_key
                self._service().store.replace_links(
                    target_stable_key(target), [])
            except Exception as exc:  # noqa: BLE001
                self._logi("清空已存链接失败: %s: %s", type(exc).__name__, exc)
        self._progress.set(0)
        self._set_status("已清空链接列表", COLORS["text_dim"])
        self._logi("清空链接: 清除 %d 条", n)
        self.toast(f"已清空 {n} 条链接" if n else "链接列表本来就是空的",
                   title="已清空", level="info")

    def _on_collect_error(self, err: str, login: bool) -> None:
        self._running = False
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._progress.set(0)
        if login:
            self._set_status("需要登录消息功能（已高亮「登录账号」按钮）", COLORS["warning"])
            self._flash_login_btn()
            self.show_error_dialog("需要登录消息功能", err,
                                   "点击左上角「登录账号」按钮，在弹出的浏览器里登录一次即可。")
        else:
            self._set_status(f"采集出错：{err[:60]}", COLORS["danger"])
            self.show_error_dialog("采集失败", err, "详细错误已写入日志。")
        self._logi("采集出错: login=%s err=%s", login, err[:120])

    def _flash_login_btn(self) -> None:
        """把「登录账号」按钮高亮闪两下，明确引导用户下一步动作。"""
        self._login_btn.configure(fg_color=COLORS["danger"],
                                  text="需要登录！点我")
        def _restore():
            try:
                self._login_btn.configure(fg_color=COLORS["warning"],
                                          text="登录账号")
            except Exception:  # noqa: BLE001
                pass
        try:
            self.after(2600, _restore)
        except Exception:  # noqa: BLE001
            pass

    def _stop(self) -> None:
        """真实停止：置位停止信号，采集器在下一轮检查时尽快退出。"""
        if not self._running:
            return
        self._stop_event.set()
        self._stop_btn.configure(state="disabled")
        self._set_status("正在停止…（当前这一轮读取完成后结束）", COLORS["warning"])
        self._logi("用户点击停止")

    # ---------------- 采集数量的记忆 ----------------
    _COUNT_CFG_KEY = "chat_last_count"

    def _load_last_count(self) -> int:
        try:
            return max(1, min(200, int(self.ctx.config.get(self._COUNT_CFG_KEY, 15))))
        except Exception:  # noqa: BLE001
            return 15

    def _save_last_count(self, n: int) -> None:
        """记住用户填的数量（下次进页/下次采集沿用）。"""
        try:
            if int(self.ctx.config.get(self._COUNT_CFG_KEY, -1)) == int(n):
                return
            self.ctx.config.set(self._COUNT_CFG_KEY, int(n))
            self.ctx.save_config()
        except Exception as exc:  # noqa: BLE001
            self._logi("保存采集数量失败: %s", exc)

    # ---------------- 复制 / 导出 ----------------
    def _copy_links(self) -> None:
        if not self._links:
            self.toast("暂无可复制的链接", title="提示", level="info")
            return
        # 一行一条：可直接粘贴到去水印工具（其输入约定为「一行一条链接」）
        text = "\n".join(self._links)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.toast(f"已复制 {len(self._links)} 条链接（一行一条）",
                   title="复制成功", level="success")
        self._logi("复制链接: %d 条", len(self._links))

    def _export_links(self) -> None:
        """把当前链接导出为 TXT（一行一条），文件名带目标名与时间。"""
        if not self._links:
            self.toast("暂无链接可导出", title="提示", level="warning")
            return
        from datetime import datetime
        from tkinter import filedialog

        target = self._selected
        safe = "".join(ch for ch in (target.name if target else "聊天")
                       if ch not in '\\/:*?"<>|').strip()[:20] or "聊天"
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        path = filedialog.asksaveasfilename(
            title="导出聊天链接", defaultextension=".txt",
            initialfile=f"聊天链接_{safe}_{stamp}.txt",
            filetypes=[("文本文件", "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._links) + "\n")
        except Exception as exc:  # noqa: BLE001
            self.show_error_dialog("导出失败", str(exc), "请换一个可写目录后重试。")
            return
        self.toast(f"已导出 {len(self._links)} 条链接", title="导出完成", level="success")
        self._logi("导出链接: %d 条 -> %s", len(self._links), path)

    def _set_status(self, text: str, color: str) -> None:
        self._status_lbl.configure(text=text, text_color=color)
