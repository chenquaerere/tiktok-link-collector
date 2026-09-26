"""主窗口：左侧导航栏（图标+高亮）+ 全局标题栏 + 页面容器 + 底部状态栏。

2026-09-25 产品化升级：
- 导航项带图标，激活态左侧紫色竖条 + 主色高亮。
- 顶部全局标题栏（品牌 + 版本 + 标语）。
- 挂载全局 ToastManager，页面通过 self.toast(...) 调用。
- minsize 降至 900×600，适配小屏。
"""
from __future__ import annotations

import queue
import threading

import customtkinter as ctk

from app.constants import APP_NAME, APP_NAME_CN, APP_VERSION

from .theme import COLORS, FONT, SPACING, RADIUS
from .components.toast import ToastManager

NAV_ITEMS = [
    ("dashboard", "▣", "仪表盘"),
    ("accounts", "◉", "账号管理"),
    ("collect", "▶", "采集任务"),
    ("chat", "✉", "聊天链接采集"),
    ("results", "▤", "采集结果"),
    ("history", "↺", "历史记录"),
    ("settings", "⚙", "设置"),
    ("logs", "≡", "日志"),
]


class AppWindow(ctk.CTk):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        # 让页面 / 组件可通过 ctx.window 拿到主窗口（用于 Toast / 对话框）
        ctx.window = self

        # 主题必须在主窗口创建之后应用（ttk.Style 依赖本窗口的解释器，
        # 提前调用会写入临时 root，导致 Treeview/Scrollbar 显示为白色）
        from .theme import apply_theme
        apply_theme(self)

        self.title(f"{APP_NAME_CN} · {APP_NAME}")
        self.geometry("1280x800")
        self.minsize(900, 600)
        self._apply_window_icon()
        self.configure(fg_color=COLORS["bg"])
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.toast = ToastManager(self)

        # 线程安全的 UI 调度队列：worker 线程禁止直接调 after()
        # （tkinter 的 after 非线程安全，会抛
        #   RuntimeError: main thread is not in main loop，
        #   表现为界面永不更新且无任何报错）。统一走 ui_call()。
        self._ui_q: "queue.Queue" = queue.Queue()
        self._ui_pump_id = None
        self._start_ui_pump()

        self._nav_buttons = {}
        self.pages = {}
        self._current = None

        self._build_sidebar()
        self._build_topbar()
        self._build_main()
        self._build_statusbar()
        self._register_pages()
        self.show_page("dashboard")
        self._schedule_auto_update_check()

    # ---- 布局 ----
    def _build_sidebar(self) -> None:
        side = ctk.CTkFrame(self, width=244, corner_radius=0, fg_color=COLORS["sidebar"])
        side.grid(row=0, column=0, sticky="nsw", rowspan=2)
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)

        # 品牌区
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=16, pady=(24, 0))
        ctk.CTkLabel(brand, text="⬡", font=(FONT["app_title"][0], 20, "bold"),
                     text_color=COLORS["primary"], width=30).pack(side="left")
        ctk.CTkLabel(brand, text=APP_NAME_CN, font=FONT["app_title"],
                     text_color=COLORS["text"], anchor="w").pack(side="left")
        ctk.CTkLabel(side, text=f"v{APP_VERSION}", font=FONT["caption"],
                     text_color=COLORS["text_faint"], anchor="w").grid(
            row=1, column=0, sticky="w", padx=16, pady=(2, 18))

        # 导航项
        for i, (key, icon, label) in enumerate(NAV_ITEMS):
            btn = ctk.CTkButton(
                side, text=f"{icon}   {label}", font=FONT["body"], anchor="w", height=40,
                corner_radius=RADIUS["sm"], fg_color="transparent",
                hover_color=COLORS["surface_alt"], text_color=COLORS["text_dim"],
                command=lambda k=key: self.show_page(k),
            )
            btn.grid(row=i + 2, column=0, sticky="ew", padx=10, pady=2)
            self._nav_buttons[key] = btn

    def _build_topbar(self) -> None:
        """顶部全局标题栏（品牌 + 标语 + 版本提示）。"""
        bar = ctk.CTkFrame(self, height=44, corner_radius=0, fg_color=COLORS["surface"])
        bar.grid(row=0, column=1, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bar, text="账号作品链接采集", font=FONT["body_strong"],
                     text_color=COLORS["text"], anchor="w").grid(
            row=0, column=0, sticky="w", padx=16)
        ctk.CTkLabel(bar, text="数据本地存储 · 严格串行采集 · 最新 N 条", font=FONT["caption"],
                     text_color=COLORS["text_faint"], anchor="e").grid(
            row=0, column=1, sticky="e", padx=16)

    def _build_main(self) -> None:
        self.content = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, height=30, corner_radius=0, fg_color=COLORS["sidebar"])
        bar.grid(row=2, column=1, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(bar, text="就绪", font=FONT["caption"],
                                         text_color=COLORS["text_dim"], anchor="w")
        self.status_label.grid(row=0, column=0, sticky="w", padx=14)
        self.status_hint = ctk.CTkLabel(bar, text="", font=FONT["caption"],
                                        text_color=COLORS["text_faint"], anchor="e")
        self.status_hint.grid(row=0, column=1, sticky="e", padx=14)

    # ---- 页面 ----
    def _register_pages(self) -> None:
        from .pages.accounts_page import AccountsPage
        from .pages.chat_page import ChatPage
        from .pages.collect_page import CollectPage
        from .pages.dashboard_page import DashboardPage
        from .pages.history_page import HistoryPage
        from .pages.logs_page import LogsPage
        from .pages.results_page import ResultsPage
        from .pages.settings_page import SettingsPage

        self.pages = {
            "dashboard": DashboardPage(self.content, self.ctx),
            "accounts": AccountsPage(self.content, self.ctx),
            "collect": CollectPage(self.content, self.ctx),
            "chat": ChatPage(self.content, self.ctx),
            "results": ResultsPage(self.content, self.ctx),
            "history": HistoryPage(self.content, self.ctx),
            "settings": SettingsPage(self.content, self.ctx),
            "logs": LogsPage(self.content, self.ctx),
        }

    def show_page(self, key: str) -> None:
        if self._current and self._current in self.pages:
            self.pages[self._current].on_leave()
            self.pages[self._current].grid_remove()
        page = self.pages[key]
        page.grid(row=0, column=0, sticky="nsew")
        page.tkraise()
        page.refresh()
        self._current = key
        for k, btn in self._nav_buttons.items():
            if k == key:
                btn.configure(fg_color=COLORS["primary_soft"], text_color=COLORS["text"],
                              border_width=0)
            else:
                btn.configure(fg_color="transparent", text_color=COLORS["text_dim"])

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    # ---- 线程安全 UI 调度 ----
    def ui_call(self, fn, *args) -> None:
        """把回调安全地排到 UI 线程执行。

        - 主线程调用：直接 after(0)
        - worker 线程调用：入队，由主线程 100ms 轮询取出执行
        """
        if threading.current_thread() is threading.main_thread():
            try:
                self.after(0, lambda: fn(*args))
                return
            except Exception:  # noqa: BLE001
                pass
        self._ui_q.put((fn, args))

    def _start_ui_pump(self) -> None:
        try:
            self._ui_pump_id = self.after(100, self._ui_pump)
        except Exception:  # noqa: BLE001
            self._ui_pump_id = None

    def _ui_pump(self) -> None:
        while True:
            try:
                fn, args = self._ui_q.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:  # noqa: BLE001
                pass
        self._start_ui_pump()

    def _apply_window_icon(self) -> None:
        """设置窗口标题栏/任务栏图标（开发态用项目 assets，frozen 用随包资源）。"""
        try:
            import sys
            from pathlib import Path

            if getattr(sys, "frozen", False):
                base = Path(sys.executable).parent / "_internal"
            else:
                base = Path(__file__).resolve().parents[2]
            ico = base / "assets" / "icon.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass  # 图标缺失不影响运行

    def notify(self, message: str, title: str = "", level: str = "info",
               duration: int = 3200) -> None:
        """快捷 Toast 入口。"""
        self.toast.show(message, title=title, level=level, duration=duration)

    # ---- 更新检查 ----
    def _schedule_auto_update_check(self) -> None:
        """启动后延迟静默检查更新（可配置开关）。"""
        if not self.ctx.config.get("auto_check_update", True):
            return
        self.after(1500, lambda: self.check_update(silent=True))

    def check_update(self, silent: bool = False) -> None:
        """后台检查更新。

        silent=True：仅在有新版本时弹窗（用于启动静默检查）；
        silent=False：无新版 / 未配置源也给出提示（用于手动按钮）。
        """
        import threading

        from .components.dialog import update_available

        if not self.ctx.resolve_update_url():
            if not silent:
                self.toast("未配置更新源，请在设置页填写 GitHub 仓库（owner/repo）",
                           title="检查更新", level="info")
            return
        self.set_status("检查更新中…")

        def worker():
            info = self.ctx.check_for_update()
            if info is None:
                if not silent:
                    self.ui_call(lambda: (
                        self.set_status("已是最新版本"),
                        self.toast("当前已是最新版本", title="检查更新", level="success"),
                    ))
                else:
                    self.ui_call(self.set_status, "就绪")
            else:
                self.ui_call(lambda: (
                    self.set_status(f"发现新版本 {info.version}"),
                    update_available(self, info.version, info.notes, info.url),
                ))

        threading.Thread(target=worker, daemon=True).start()

