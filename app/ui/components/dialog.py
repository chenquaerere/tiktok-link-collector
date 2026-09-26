"""样式化对话框：替代原生 messagebox，保持与主题一致。

- confirm：确认弹窗（危险操作红色按钮），返回 bool。
- info：需用户确认的信息弹窗（少量关键信息仍可用）。
- error：错误弹窗（标题 + 原因 + 建议，详情建议写日志）。
"""
from __future__ import annotations

import customtkinter as ctk

from ..theme import COLORS, FONT, RADIUS, SPACING

_ICONS = {
    "info":    ("ℹ", COLORS["info"]),
    "warning": ("⚠", COLORS["warning"]),
    "danger":  ("✕", COLORS["danger"]),
}


def _modal(win) -> None:
    """把窗口变成模态弹窗。

    ⚠️ 加固点（2026-09-26）：
    - `grab_set` 在窗口尚未 viewable 时会抛 TclError（"grab failed"），
      异常会顺着按钮回调冒泡被 tkinter 吞掉 → 用户看到「点了没反应」。
      这里吞掉异常并改用 topmost 兜底，保证弹窗一定能被看见。
    - 置顶 + 延迟再次 lift/focus，避免弹窗被主窗口遮住（遮住时主窗口被
      grab 卡住、用户以为程序没反应）。
    """
    try:
        win.transient(win.master)
    except Exception:
        pass
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass
    try:
        win.grab_set()
    except Exception:
        pass          # grab 失败不再中断后续流程（只损失「父窗口不可点」）
    win.lift()
    try:
        win.focus_force()
    except Exception:
        pass

    def _re_lift():
        try:
            win.lift()
            win.attributes("-topmost", True)
        except Exception:
            pass
    try:
        win.after(120, _re_lift)
    except Exception:
        pass


def confirm(master, title: str, message: str, danger: bool = False,
            ok_text: str = "确认", cancel_text: str = "取消") -> bool:
    """确认对话框。返回 True=确认，False=取消。"""
    top = master.winfo_toplevel() if master else None
    win = ctk.CTkToplevel(top)
    win.title(title)
    win.geometry("440x230")
    win.resizable(False, False)
    win.configure(fg_color=COLORS["surface"])

    kind = "danger" if danger else "warning"
    icon, color = _ICONS[kind]

    head = ctk.CTkFrame(win, fg_color="transparent")
    head.pack(fill="x", padx=24, pady=(22, 8))
    ctk.CTkLabel(head, text=icon, font=(FONT["app_title"][0], 22, "bold"),
                 text_color=color, width=40).pack(side="left", anchor="n")
    ctk.CTkLabel(head, text=title, font=FONT["body_strong"],
                 text_color=COLORS["text"], anchor="w").pack(side="left", pady=(4, 0))

    ctk.CTkLabel(win, text=message, font=FONT["body"], text_color=COLORS["text_dim"],
                 anchor="w", justify="left", wraplength=390).pack(
        fill="x", padx=24, pady=(4, 12))

    btns = ctk.CTkFrame(win, fg_color="transparent")
    btns.pack(side="bottom", anchor="e", padx=24, pady=(0, 20))

    result = {"ok": False}

    def _ok():
        result["ok"] = True
        win.destroy()

    ctk.CTkButton(btns, text=ok_text, width=96, height=36,
                  fg_color=COLORS["danger"] if danger else COLORS["primary"],
                  hover_color=COLORS["danger_hover"] if danger else COLORS["primary_hover"],
                  command=_ok).pack(side="left", padx=4)
    ctk.CTkButton(btns, text=cancel_text, width=96, height=36,
                  fg_color=COLORS["surface_alt"], hover_color=COLORS["border"],
                  command=win.destroy).pack(side="left", padx=4)

    _modal(win)
    win.wait_window()
    return result["ok"]


def info(master, title: str, message: str, ok_text: str = "知道了") -> None:
    """信息弹窗（单按钮）。"""
    top = master.winfo_toplevel() if master else None
    win = ctk.CTkToplevel(top)
    win.title(title)
    win.geometry("440x220")
    win.resizable(False, False)
    win.configure(fg_color=COLORS["surface"])

    head = ctk.CTkFrame(win, fg_color="transparent")
    head.pack(fill="x", padx=24, pady=(22, 8))
    ctk.CTkLabel(head, text="ℹ", font=(FONT["app_title"][0], 22, "bold"),
                 text_color=COLORS["info"], width=40).pack(side="left", anchor="n")
    ctk.CTkLabel(head, text=title, font=FONT["body_strong"],
                 text_color=COLORS["text"], anchor="w").pack(side="left", pady=(4, 0))

    ctk.CTkLabel(win, text=message, font=FONT["body"], text_color=COLORS["text_dim"],
                 anchor="w", justify="left", wraplength=390).pack(
        fill="x", padx=24, pady=(4, 12))

    ctk.CTkButton(win, text=ok_text, width=96, height=36, fg_color=COLORS["primary"],
                  hover_color=COLORS["primary_hover"], command=win.destroy).pack(
        side="bottom", anchor="e", padx=24, pady=(0, 20))
    _modal(win)


def error(master, title: str, message: str, suggestion: str = "") -> None:
    """错误弹窗：标题 + 原因 + 建议（详情写日志）。"""
    top = master.winfo_toplevel() if master else None
    win = ctk.CTkToplevel(top)
    win.title(title)
    win.resizable(False, False)
    win.configure(fg_color=COLORS["surface"])

    head = ctk.CTkFrame(win, fg_color="transparent")
    head.pack(fill="x", padx=24, pady=(22, 8))
    ctk.CTkLabel(head, text="✕", font=(FONT["app_title"][0], 22, "bold"),
                 text_color=COLORS["danger"], width=40).pack(side="left", anchor="n")
    ctk.CTkLabel(head, text=title, font=FONT["body_strong"],
                 text_color=COLORS["text"], anchor="w").pack(side="left", pady=(4, 0))

    body = ctk.CTkFrame(win, fg_color="transparent")
    body.pack(fill="x", padx=24, pady=(4, 8))
    ctk.CTkLabel(body, text=message, font=FONT["body"], text_color=COLORS["text_dim"],
                 anchor="w", justify="left", wraplength=390).pack(anchor="w")
    if suggestion:
        ctk.CTkLabel(body, text=suggestion, font=FONT["secondary"],
                     text_color=COLORS["accent"], anchor="w", justify="left",
                     wraplength=390).pack(anchor="w", pady=(8, 0))

    ctk.CTkButton(win, text="知道了", width=96, height=36, fg_color=COLORS["primary"],
                  hover_color=COLORS["primary_hover"], command=win.destroy).pack(
        side="bottom", anchor="e", padx=24, pady=(0, 20))

    # 动态调高窗口以容纳内容
    win.update_idletasks()
    h = max(200, win.winfo_reqheight() + 24)
    win.geometry(f"440x{h}")
    _modal(win)


def update_available(master, version: str, notes: str, download_url: str) -> None:
    """「发现新版本」弹窗：显示版本与说明，提供「查看下载」与「暂不」按钮。"""
    import webbrowser

    top = master.winfo_toplevel() if master else None
    win = ctk.CTkToplevel(top)
    win.title("发现新版本")
    win.geometry("460x360")
    win.resizable(False, False)
    win.configure(fg_color=COLORS["surface"])

    head = ctk.CTkFrame(win, fg_color="transparent")
    head.pack(fill="x", padx=24, pady=(22, 8))
    ctk.CTkLabel(head, text="⬆", font=(FONT["app_title"][0], 22, "bold"),
                 text_color=COLORS["info"], width=40).pack(side="left", anchor="n")
    ctk.CTkLabel(head, text=f"发现新版本  {version}", font=FONT["body_strong"],
                 text_color=COLORS["text"], anchor="w").pack(side="left", pady=(4, 0))

    # 更新说明（可滚动，notes 可能很长）
    body = ctk.CTkScrollableFrame(win, fg_color=COLORS["surface_alt"], corner_radius=8,
                                  height=180)
    body.pack(fill="both", expand=True, padx=24, pady=(4, 8))
    text = notes.strip() or "（未提供更新说明）"
    ctk.CTkLabel(body, text=text, font=FONT["body"], text_color=COLORS["text_dim"],
                 anchor="w", justify="left", wraplength=360).pack(
        anchor="w", padx=14, pady=12)

    btns = ctk.CTkFrame(win, fg_color="transparent")
    btns.pack(side="bottom", anchor="e", padx=24, pady=(0, 20))

    def _open():
        if download_url:
            try:
                webbrowser.open(download_url)
            except Exception:
                pass
        win.destroy()

    ctk.CTkButton(btns, text="查看下载", width=110, height=36, fg_color=COLORS["primary"],
                  hover_color=COLORS["primary_hover"], command=_open).pack(side="left", padx=4)
    ctk.CTkButton(btns, text="暂不", width=96, height=36, fg_color=COLORS["surface_alt"],
                  hover_color=COLORS["border"], command=win.destroy).pack(side="left", padx=4)

    _modal(win)
