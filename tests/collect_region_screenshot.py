# -*- coding: utf-8 -*-
"""采集任务页「按地区选择账号」效果截图：地区选中「越南」时的状态。"""
import sys

sys.path.insert(0, r"D:\TikTokLinkCollector")

import tempfile
from pathlib import Path

from app.app import AppServices
from app.core.models import Account
from app.ui.app_window import AppWindow

tmp = Path(tempfile.mkdtemp(prefix="collect_shot_"))
ctx = AppServices(base_dir=tmp)

DATA = [
    ("nguyen.van.a", "越南", "小阮"), ("tran.thi.b", "越南", "阿珍"),
    ("le.minh.c", "越南", "Minh"),
    ("aung.ko.ko", "缅甸", "昂哥哥"), ("su.myat", "缅甸", "Myat"),
    ("somchai.t", "泰国", "Somchai"),
    ("user_x1", "", "无名氏"),
]
for u, region, nick in DATA:
    ctx.db.insert_account(Account(
        account_id=u, username=u, profile_url=f"https://www.tiktok.com/@{u}",
        region=region, display_name=nick, collect_count=4))

app = AppWindow(ctx)
app.geometry("1280x860")
app.show_page("collect")
for _ in range(6):
    app.update_idletasks()
    app.update()

page = app.pages["collect"]
page._region_filter.set("越南")
page._on_region_changed()
for _ in range(5):
    app.update_idletasks()
    app.update()

out = r"D:/TikTokLinkCollector/diagnostics/collect_region_ui.png"
try:
    from PIL import ImageGrab
    x, y = app.winfo_rootx(), app.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height())).save(out)
    print("saved:", out)
    print("当前地区:", page._region_filter.get())
    print("显示账号:", sorted(page._checkboxes))
    print("已勾选:", sorted(page._checked_ids))
except Exception as e:  # noqa: BLE001
    print("grab fail:", e)
app.destroy()
