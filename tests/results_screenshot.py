# -*- coding: utf-8 -*-
"""采集结果页效果截图：① 启动态（空） ② 本次采集（只显示本次 3 条 + 绿色最近采集时间）。

用途：给用户确认「只显示本次采集」与「采集时间/排序」的实际效果。
"""
import sys

sys.path.insert(0, r"D:\TikTokLinkCollector")

import tempfile
from pathlib import Path

from app.app import AppServices
from app.core.models import Account, Video
from app.ui.app_window import AppWindow

_tmp = Path(tempfile.mkdtemp(prefix="results_shot_"))
ctx = AppServices(base_dir=_tmp)

for u, region, nick in [("nguyen.van.a", "越南", "小阮"), ("aung.ko.ko", "缅甸", "昂哥")]:
    ctx.db.insert_account(Account(
        account_id=u, username=u, profile_url=f"https://www.tiktok.com/@{u}",
        region=region, display_name=nick, collect_count=4))

ctx.db.insert_task("t_old", target_date="2026-09-20", status="completed")
ctx.db.insert_task("t_new", target_date="2026-09-27", status="completed")

# 历史数据（上一次任务，5 条）——不应出现在「本次采集」里
for i in range(5):
    ctx.db.insert_video(Video(
        video_id=f"9000000000000000{i}", account_id="nguyen.van.a", username="nguyen.van.a",
        video_url=f"https://www.tiktok.com/@nguyen.van.a/video/9000000000000000{i}",
        publish_time=f"2026-09-1{i} 10:00:00", publish_date=f"2026-09-1{i}",
        first_collect_time=f"2026-09-20 09:0{i}:00", first_task_id="t_old"))

# 本次采集：1 个账号 3 条
NOW = "2026-09-27 14:05:12"
for i in range(3):
    ctx.db.insert_video(Video(
        video_id=f"80000000000000000{i}", account_id="aung.ko.ko", username="aung.ko.ko",
        video_url=f"https://www.tiktok.com/@aung.ko.ko/video/80000000000000000{i}",
        publish_time=f"2026-09-2{6 - i} 18:3{i}:00", publish_date=f"2026-09-2{6 - i}",
        first_collect_time=NOW, first_task_id="t_new"))

app = AppWindow(ctx)
app.geometry("1280x820")
app.show_page("results")
for _ in range(8):
    app.update_idletasks()
    app.update()
page = app.pages["results"]


def grab(path: str) -> None:
    try:
        x, y = app.winfo_rootx(), app.winfo_rooty()
        w, h = app.winfo_width(), app.winfo_height()
        from PIL import ImageGrab
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
        print("saved:", path)
    except Exception as e:  # noqa: BLE001
        print("grab fail:", e)


# ① 启动态：结果区为空
grab(r"D:/TikTokLinkCollector/diagnostics/results_idle_ui.png")
print("启动态 —— 表格显示:", bool(page._table.grid_info()),
      "| 提示:", repr(page._count_lbl.cget("text")))

# ② 本次采集完成：只显示本次 3 条
ctx.collected_this_session = True
ctx.last_task_id = "t_new"
page.refresh()
for _ in range(6):
    app.update_idletasks()
    app.update()
grab(r"D:/TikTokLinkCollector/diagnostics/results_collect_time_ui.png")
print("本次采集 —— 行数:", page._table.row_count(),
      "| 计数:", repr(page._count_lbl.cget("text")),
      "| 最近采集:", repr(page._latest_lbl.cget("text")))
app.destroy()
