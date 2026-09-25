"""UI 主题与设计 token（深色主题，克制的高级感配色）。

设计语言参考：深空科技色系，主色紫、强调青，红=涨/危险、绿=成功（中国习惯）。
所有颜色集中在 COLORS，页面与组件统一从这里取值，避免散落硬编码。

2026-09-25 产品化升级：补全 Design Tokens（间距/圆角/状态软色/hover 态）、
9 级字体层级，并提供 Windows 高 DPI 适配。
"""
from __future__ import annotations

import sys

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk

# ---- 配色 token ----
COLORS = {
    # 背景 / 表面
    "bg":            "#0f1117",   # 主背景
    "sidebar":       "#141824",   # 左侧导航
    "surface":       "#1a1e2b",   # 卡片 / 表面
    "surface_alt":   "#212635",   # 悬停 / 次级表面
    "surface_hover": "#2a3142",   # 表格行悬停
    "border":        "#2a3040",   # 边框

    # 品牌
    "primary":       "#6c63ff",   # 主色（紫）
    "primary_hover": "#5a52e0",
    "primary_soft":  "#2a2654",   # 主色软底（选中/徽章背景）
    "accent":        "#3ecfcf",   # 强调（青）
    "accent_hover":  "#2fb0b0",
    "accent_soft":   "#163d3d",

    # 文字
    "text":          "#e6e8ee",   # 主文字
    "text_dim":      "#9aa3b5",   # 次级文字
    "text_faint":    "#6b7280",   # 弱文字

    # 状态
    "success":       "#22c55e",
    "success_hover": "#1da750",
    "success_soft":  "#163b27",
    "warning":       "#f59e0b",
    "warning_hover": "#d98b06",
    "warning_soft":  "#3d2f12",
    "danger":        "#ef4444",
    "danger_hover":  "#c53030",
    "danger_soft":   "#3d1c1c",
    "info":          "#3b82f6",
    "info_hover":    "#2f6fd6",
    "info_soft":     "#172a4d",
}

# ---- 间距 token（4 的倍数）----
SPACING = {
    "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 20, "xxl": 24, "xxxl": 32,
}

# ---- 圆角 token ----
RADIUS = {
    "sm": 8, "md": 10, "lg": 12, "xl": 16, "pill": 20,
}

# ---- 字体 ----
FONT_FAMILY = "Microsoft YaHei UI"
FONT_MONO = "Consolas"

# 9 级字体层级（App Title / Page Title / Section / Body / Body Strong /
#            Secondary / Caption / Button / Table / Number / Mono）
FONT = {
    "app_title":    (FONT_FAMILY, 17, "bold"),
    "page_title":   (FONT_FAMILY, 22, "bold"),
    "section":      (FONT_FAMILY, 16, "bold"),
    "body":         (FONT_FAMILY, 13),
    "body_strong":  (FONT_FAMILY, 13, "bold"),
    "secondary":    (FONT_FAMILY, 12),
    "caption":      (FONT_FAMILY, 11),
    "button":       (FONT_FAMILY, 13),
    "table":        (FONT_FAMILY, 13),
    "number":       (FONT_FAMILY, 28, "bold"),
    "mono":         (FONT_MONO, 12),
}

# 向后兼容的旧别名（既有代码 / 测试仍引用）
FONT_SMALL = FONT["secondary"]
FONT_BODY = FONT["body"]
FONT_TITLE = FONT["section"]
FONT_H1 = FONT["page_title"]
FONT_NUM = FONT["number"]


def enable_high_dpi() -> None:
    """启用 Windows 高 DPI 感知，避免 125%/150% 缩放下字体/控件模糊。

    在创建任何 Tk 窗口之前调用（main / run 入口）。非 Windows 或失败时静默忽略。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # 优先 Per-Monitor v2，回退 System DPI Aware
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def apply_theme(master=None) -> None:
    """应用全局深色主题（customtkinter appearance + ttk.Treeview/Scrollbar 样式）。

    重要：必须在主窗口（CTk root）创建之后调用，并把窗口实例作为 master 传入。
    若在无 root 时调用，ttk.Style() 会隐式创建临时 Tk root，样式将写入
    错误的解释器，导致 Treeview 回退为系统默认白色主题（历史 bug）。
    """
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")  # 基础主题，具体颜色在组件上覆盖

    style = ttk.Style(master)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Treeview",
        background=COLORS["surface"],
        fieldbackground=COLORS["surface"],
        foreground=COLORS["text"],
        borderwidth=0,
        rowheight=32,
        font=FONT["table"],
    )
    style.configure(
        "Treeview.Heading",
        background=COLORS["surface_alt"],
        foreground=COLORS["text_dim"],
        borderwidth=0,
        font=(FONT_FAMILY, 12, "bold"),
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", COLORS["primary"])],
        foreground=[("selected", "#ffffff")],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", COLORS["surface_alt"])],
        foreground=[("active", COLORS["text"])],
    )
    # ttk 滚动条深色化（clam 主题下默认为系统白）
    style.configure(
        "Vertical.TScrollbar",
        background=COLORS["surface_alt"],
        troughcolor=COLORS["surface"],
        bordercolor=COLORS["surface"],
        arrowcolor=COLORS["text_dim"],
        relief="flat",
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", COLORS["border"]), ("pressed", COLORS["primary"])],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=COLORS["surface_alt"],
        troughcolor=COLORS["surface"],
        bordercolor=COLORS["surface"],
        arrowcolor=COLORS["text_dim"],
        relief="flat",
    )
