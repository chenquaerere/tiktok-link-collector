# -*- coding: utf-8 -*-
"""聊天页新布局截图：构建主窗口 → 切到聊天页 → 截图落盘。"""
import sys

sys.path.insert(0, r"D:\TikTokLinkCollector")

import tempfile
from pathlib import Path

from app.app import AppServices
from app.ui.app_window import AppWindow

_tmp = tempfile.mkdtemp(prefix="chat_ui_shot_")
ctx = AppServices(base_dir=Path(_tmp))
app = AppWindow(ctx)
app.geometry("1200x780")

app.show_page("chat")
app.update_idletasks()
app.update()
app.after(600, lambda: None)
app.update_idletasks()
app.update()

out = r"D:/TikTokLinkCollector/diagnostics/chat_ui_v12.png"
try:
    import tkinter as tk
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    w = app.winfo_width()
    h = app.winfo_height()
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(out)
    print("saved:", out)
except Exception as e:
    print("grab fail:", e)
app.destroy()
