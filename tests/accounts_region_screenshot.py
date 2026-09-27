# -*- coding: utf-8 -*-
"""账号管理页「地区分类」效果截图：造样例数据 → 打开账号页 → 截图落盘。

用途：给用户确认 UI 效果（列布局、地区聚集排序、统计、筛选下拉）。
"""
import sys

sys.path.insert(0, r"D:\TikTokLinkCollector")

import tempfile
from pathlib import Path

from app.app import AppServices
from app.core.models import Account
from app.ui.app_window import AppWindow

_tmp = Path(tempfile.mkdtemp(prefix="acct_region_shot_"))
ctx = AppServices(base_dir=_tmp)

# 样例数据：越南 4 / 缅甸 3 / 泰国 2 / 自定义「巴西」2 / 未分类 3（带昵称）
SAMPLE = [
    ("nguyen.van.a", "越南", "小阮"), ("tranthi.b", "越南", "阿珍"),
    ("le.minh.c", "越南", "Minh"), ("pham.d", "越南", ""),
    ("aung.ko.ko", "缅甸", "昂哥哥"), ("su.myat", "缅甸", "Myat"),
    ("zaw.htet", "缅甸", ""),
    ("somchai.t", "泰国", "Somchai"), ("ploi.j", "泰国", "Ploi"),
    ("lucas.br", "巴西", "Lucas"), ("ana.silva", "巴西", "Ana"),
    ("user_x1", "", "无名氏"), ("user_x2", "", ""), ("user_x3", "", ""),
]
for i, (u, region, nickname) in enumerate(SAMPLE):
    ctx.db.insert_account(Account(
        account_id=u, username=u,
        profile_url=f"https://www.tiktok.com/@{u}",
        region=region,
        display_name=nickname,
        collect_count=4,
        remark=f"备注{i + 1}" if i % 3 == 0 else ""))

app = AppWindow(ctx)
app.geometry("1280x820")
app.show_page("accounts")
for _ in range(8):
    app.update_idletasks()
    app.update()

out = r"D:/TikTokLinkCollector/diagnostics/accounts_region_ui.png"
try:
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    from PIL import ImageGrab
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(out)
    print("saved:", out)
    print("表格行数:", app.pages["accounts"].table.row_count())
    print("统计:", repr(app.pages["accounts"]._region_lbl.cget("text")))
except Exception as e:  # noqa: BLE001
    print("grab fail:", e)
app.destroy()
