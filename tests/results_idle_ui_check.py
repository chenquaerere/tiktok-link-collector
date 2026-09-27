"""采集结果页 UI 检查（源码态，无需网络/浏览器）。

覆盖两轮用户反馈：
A. 启动必须清空（上一轮）
B. 默认只显示「本次采集」的链接 —— 只采 1 个账号 3 条，不能列出一堆历史；
   排序按「采集时间」倒序；底部显示最近采集时间（绿色）。
"""
import sys

sys.path.insert(0, r"D:\TikTokLinkCollector")

import tempfile
from pathlib import Path

from app.app import AppServices
from app.core.models import Account, Video
from app.ui.app_window import AppWindow

PASS, FAIL = [], []
TASK_OLD, TASK_NEW = "task_old", "task_new"


def check(cond, msg):
    (PASS if cond else FAIL).append(msg)
    print(("  PASS  " if cond else "  FAIL  ") + msg)


def settle(app, n=6):
    for _ in range(n):
        app.update_idletasks()
        app.update()


tmp = Path(tempfile.mkdtemp(prefix="results_scope_ui_"))
ctx = AppServices(base_dir=tmp)

for u in ("acct_old", "acct_new"):
    ctx.db.insert_account(Account(account_id=u, username=u,
                                  profile_url=f"https://www.tiktok.com/@{u}"))

# videos.first_task_id 有外键约束 → 先建任务记录
ctx.db.insert_task(TASK_OLD, target_date="2026-09-20", status="completed")
ctx.db.insert_task(TASK_NEW, target_date="2026-09-27", status="completed")

# 旧历史：acct_old 5 条（上一次任务采的）
for i in range(5):
    ctx.db.insert_video(Video(
        video_id=f"9000000000000000{i}", account_id="acct_old", username="acct_old",
        video_url=f"https://www.tiktok.com/@acct_old/video/9000000000000000{i}",
        publish_time=f"2026-09-1{i} 10:00:00", publish_date=f"2026-09-1{i}",
        first_collect_time=f"2026-09-20 09:0{i}:00", first_task_id=TASK_OLD))

# 本次任务：acct_new 3 条（采集时间与发布时间故意反序，用于验证排序依据）
NEW = [
    ("800000000000000001", "2026-09-27 14:00:01", "2026-09-20 10:00:00"),
    ("800000000000000002", "2026-09-27 14:00:03", "2026-09-10 10:00:00"),
    ("800000000000000003", "2026-09-27 14:00:02", "2026-09-25 10:00:00"),
]
for vid, ct, pt in NEW:
    ctx.db.insert_video(Video(
        video_id=vid, account_id="acct_new", username="acct_new",
        video_url=f"https://www.tiktok.com/@acct_new/video/{vid}",
        publish_time=pt, publish_date=pt[:10],
        first_collect_time=ct, first_task_id=TASK_NEW))

check(ctx.db.count_videos() == 8, f"测试数据就绪：库中共 8 条（旧 5 + 本次 3，实得 {ctx.db.count_videos()}）")

app = AppWindow(ctx)
app.geometry("1280x820")
app.show_page("results")
settle(app)
page = app.pages["results"]
cols = list(page._table.columns)

print("\n--- 1) 表格结构 ---")
check("collect_time" in cols, f"表格含「采集时间」列（列: {cols}）")
check(str(page._table.tree.heading("collect_time")["text"]) == "采集时间", "表头文字为「采集时间」")

print("\n--- 2) 启动态：结果区必须为空 ---")
check(not page._table.grid_info(), "启动时结果表格隐藏")
check(not page._link_panel.grid_info(), "启动时链接面板隐藏")
check(page._rows == [], "内存中无链接行")
check(bool(page._idle.grid_info()), "显示「本次尚未采集」")
check(page._scope_menu.get() == "本次采集", "数据范围默认「本次采集」")

print("\n--- 3) 本次采集后：只显示本次 3 条（核心）---")
ctx.collected_this_session = True
ctx.last_task_id = TASK_NEW
page.refresh()
settle(app)
n = page._table.row_count()
check(n == 3, f"只显示本次任务的 3 条（实得 {n}，旧账号 5 条不应出现）")
ids = [str(page._table.get_values(i)[cols.index("video_id")])
       for i in page._table.all_iids()]
check(all(i.startswith("8000") for i in ids), f"行内全部是本次任务的视频（实得 {ids}）")
check(not any(i.startswith("9000") for i in ids), "无任何历史任务的视频")

print("\n--- 4) 排序：按采集时间倒序（刚采的在最前）---")
cts = [str(page._table.get_values(i)[cols.index("collect_time")])
       for i in page._table.all_iids()]
check(cts == sorted(cts, reverse=True), f"采集时间倒序（实得 {cts}）")
check("14:00:03" in cts[0], f"第一条是最新采集时间（实得 {cts[0]!r}）")

print("\n--- 5) 底部显示最近采集时间（绿色）---")
from app.ui.theme import COLORS as _C   # noqa: E402
latest = str(page._latest_lbl.cget("text"))
check(latest.startswith("最近采集"), f"显示「最近采集 …」（实得 {latest!r}）")
check("2026-09-27 14:00:03" in latest, "取的是本次最大采集时间")
check(str(page._latest_lbl.cget("text_color")).lower() == str(_C["success"]).lower(),
      f"时间用 success 绿色（实得 {page._latest_lbl.cget('text_color')} / 期望 {_C['success']}）")
check(str(page._count_lbl.cget("text_color")).lower() != str(_C["success"]).lower(),
      "「共 N 条」保持灰色，只有时间高亮")

print("\n--- 6) 切到「全部历史」可回看以前采集的 ---")
page._scope_menu.set("全部历史")
page._on_scope_changed()
settle(app)
check(page._table.row_count() == 8, f"全部历史显示 8 条（实得 {page._table.row_count()}）")
page._scope_menu.set("本次采集")
page._on_scope_changed()
settle(app)
check(page._table.row_count() == 3, f"切回本次采集仍是 3 条（实得 {page._table.row_count()}）")

print("\n--- 7) 重开程序：依然为空（标记不落盘）---")
app.destroy()
ctx.close()
ctx2 = AppServices(base_dir=tmp)
app2 = AppWindow(ctx2)
app2.geometry("1280x820")
app2.show_page("results")
settle(app2)
page2 = app2.pages["results"]
check(not page2._table.grid_info(), "重开后表格隐藏")
check(page2._rows == [], "重开后无链接行")
check(bool(page2._idle.grid_info()), "重开后显示「本次尚未采集」")
check(ctx2.db.count_videos() == 8, "数据库数据完好（只是不显示）")
check(getattr(ctx2, "last_task_id", "") == "", "任务 ID 标记不落盘（重开为空）")
app2.destroy()
ctx2.close()

print(f"\n=== PASS {len(PASS)} / FAIL {len(FAIL)} ===")
for m in FAIL:
    print("  FAILED:", m)
sys.exit(1 if FAIL else 0)
