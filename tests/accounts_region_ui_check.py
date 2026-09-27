"""账号管理页「地区分类」UI 检查（源码态，不需要网络与浏览器）。

覆盖：
1. 地区列渲染正确（未分类空值显示为「未分类」）
2. 按地区聚集排序（预置顺序 → 自定义 → 未分类最后）
3. 地区筛选下拉生效且包含预置地区 + 自定义地区 + 未分类
4. 地区统计文案生成
5. 添加账号时带地区
6. 批量设置地区 → 表格实时更新
7. 「设置地区」弹窗可正常构造与销毁（不崩、不残留）
8. 旧结构库（无 region 列）打开不崩
"""
import sys

sys.path.insert(0, r"D:\TikTokLinkCollector")

import os
import sqlite3
import tempfile
from pathlib import Path

from app.app import AppServices
from app.core.models import Account
from app.ui.app_window import AppWindow

PASS, FAIL = [], []


def check(cond, msg):
    (PASS if cond else FAIL).append(msg)
    print(("  PASS  " if cond else "  FAIL  ") + msg)


tmp = Path(tempfile.mkdtemp(prefix="acct_region_ui_"))
ctx = AppServices(base_dir=tmp)

# 造数据：越南 3 / 缅甸 2 / 自定义「巴西」1 / 未分类 2（部分带昵称）
for u, region, nickname in [
    ("vn_one", "越南", "越南小美"), ("vn_two", "越南", ""), ("vn_three", "越南", "Ngoc"),
    ("mm_one", "缅甸", "缅甸小哥"), ("mm_two", "缅甸", ""),
    ("br_one", "巴西", ""),
    ("none_one", "", "无名氏"), ("none_two", "", ""),
]:
    ctx.db.insert_account(Account(
        account_id=u, username=u, profile_url=f"https://www.tiktok.com/@{u}",
        region=region, display_name=nickname))

app = AppWindow(ctx)
app.geometry("1280x820")
app.show_page("accounts")
for _ in range(6):
    app.update_idletasks()
    app.update()

page = app.pages["accounts"]

print("\n--- 1) 表格结构 ---")
cols = list(page.table.columns)
check("region" in cols, f"表格含 region 列（列: {cols}）")
check("nickname" in cols, "表格含 nickname（昵称）列")
check(cols.index("nickname") == 0, "昵称列排在最前（用户要求：昵称在前）")
check(cols.index("username") == 1, "账号列紧随昵称列")
check(cols.index("region") == 2, "地区列排第 3 位")

# 用列名定位索引：列顺序变化时脚本无需跟着改
NICK_IDX = cols.index("nickname")
REGION_IDX = cols.index("region")

print("\n--- 1b) 昵称渲染 + 刷新按钮 ---")
rows_n = [page.table.get_values(i) for i in page.table.all_iids()]
nicks = {r[NICK_IDX] for r in rows_n}
check("越南小美" in nicks, f"昵称列渲染正确（实得 {sorted(nicks)}）")
check("无名氏" in nicks, "未分类账号的昵称也能显示")
check("—" in nicks, "无昵称的账号显示占位符「—」")
check(page._nick_btn.cget("text") == "刷新昵称", "「刷新昵称」按钮存在")
check(page._nick_running is False, "昵称任务初始不在运行态")

print("\n--- 2) 地区渲染 + 聚集排序 ---")
rows = [page.table.get_values(i) for i in page.table.all_iids()]
regions_col = [r[REGION_IDX] for r in rows]
print("  地区列顺序:", regions_col)
check(len(rows) == 8, f"8 个账号全部渲染（实得 {len(rows)}）")
check("未分类" in regions_col, "空地区显示为「未分类」")
# 同一地区的行必须相邻（= 视觉分类）
seen, ok_cluster = [], True
for r in regions_col:
    if not seen or seen[-1] != r:
        if r in seen:
            ok_cluster = False
        seen.append(r)
check(ok_cluster, "同地区账号相邻聚集（未出现交错）")
check(regions_col[0] == "越南", "预置地区按预置顺序排在前面")
check(regions_col[-1] == "未分类", "未分类排在最后")

print("\n--- 3) 地区筛选 ---")
opts = list(page.region_filter.cget("values"))
print("  下拉选项:", opts)
for want in ("全部地区", "越南", "缅甸", "巴西", "未分类"):
    check(want in opts, f"筛选下拉包含「{want}」")

page.region_filter.set("越南")
page._render()
app.update_idletasks()
check(page.table.row_count() == 3, f"筛选「越南」应为 3 行（实得 {page.table.row_count()}）")

page.region_filter.set("未分类")
page._render()
app.update_idletasks()
check(page.table.row_count() == 2, f"筛选「未分类」应为 2 行（实得 {page.table.row_count()}）")

page.region_filter.set("全部地区")
page._render()
app.update_idletasks()
check(page.table.row_count() == 8, "恢复「全部地区」应为 8 行")

print("\n--- 4) 统计文案 ---")
stat_text = page._region_lbl.cget("text")
print("  统计标签:", repr(stat_text))
check("越南3" in stat_text, "统计含「越南3」")
check("缅甸2" in stat_text, "统计含「缅甸2」")

print("\n--- 5) 添加账号带地区 ---")
page.entry.delete(0, "end")
page.entry.insert(0, "adding_new")
page.add_region.set("缅甸")
page._add()
app.update_idletasks()
row = ctx.db.get_account("adding_new")
check(row is not None and row["region"] == "缅甸",
      f"新增账号地区应为缅甸（实得 {row['region'] if row else 'N/A'}）")

print("\n--- 6) 批量设置地区 ---")
sel = [i for i in page.table.all_iids()
       if page.table.get_values(i)[REGION_IDX] == "未分类"]
check(len(sel) == 2, f"选中 2 个未分类账号（实得 {len(sel)}）")
n = ctx.account_service.set_regions(sel, "越南")
page._render()
app.update_idletasks()
check(n == 2, f"批量设置影响 2 行（实得 {n}）")
check(ctx.db.get_account("none_one")["region"] == "越南", "none_one 已归类到越南")
expect_rows = ctx.db.count_accounts()
check(page.table.row_count() == expect_rows,
      f"重渲染后行数与库一致（表格 {page.table.row_count()} / 库 {expect_rows}）")

print("\n--- 7) 设置地区弹窗（构造 + 销毁） ---")
page.table.tree.selection_set(page.table.all_iids()[:1])
before = len(app.winfo_children())
try:
    page._set_region()
    app.update_idletasks()
    app.update()
    tops = [w for w in app.winfo_children() if isinstance(w, __import__("tkinter").Toplevel)]
    check(len(tops) >= 1, f"弹窗已创建（Toplevel 数 {len(tops)}）")
    for w in tops:
        w.destroy()
    app.update_idletasks()
    check(len([w for w in app.winfo_children()
               if isinstance(w, __import__("tkinter").Toplevel)]) == 0,
          "弹窗销毁后无残留")
except Exception as e:  # noqa: BLE001
    check(False, f"设置地区弹窗异常: {type(e).__name__}: {e}")

print("\n--- 8) 未选中时点设置地区应给提示而非报错 ---")
page.table.tree.selection_remove(page.table.all_iids())
try:
    page._set_region()
    check(True, "未选中时安全返回（无异常）")
except Exception as e:  # noqa: BLE001
    check(False, f"未选中时抛异常: {e!r}")

app.destroy()

print("\n--- 9) 旧结构库（无 region 列）打开不崩 ---")
legacy_dir = Path(tempfile.mkdtemp(prefix="legacy_ui_"))
legacy_db = legacy_dir / "old.db"
conn = sqlite3.connect(legacy_db)
conn.executescript("""
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    profile_url TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    remark TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    login_status TEXT NOT NULL DEFAULT 'unknown',
    collect_count INTEGER NOT NULL DEFAULT 4,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    last_collect_time TEXT,
    last_collect_result TEXT NOT NULL DEFAULT ''
);
INSERT INTO accounts(account_id, username, profile_url)
VALUES('legacy1','legacy1','https://www.tiktok.com/@legacy1');
PRAGMA user_version = 2;
""")
conn.commit()
conn.close()

ctx2 = AppServices(base_dir=legacy_dir)
ctx2.db = __import__("app.db.database", fromlist=["Database"]).Database(str(legacy_db))
ctx2.account_service = __import__(
    "app.services.account_service", fromlist=["AccountService"]
).AccountService(ctx2.db)
app2 = AppWindow(ctx2)
app2.geometry("1280x820")
app2.show_page("accounts")
for _ in range(5):
    app2.update_idletasks()
    app2.update()
p2 = app2.pages["accounts"]
check(p2.table.row_count() == 1, f"旧库账号仍显示（实得 {p2.table.row_count()}）")
_legacy_cols = list(p2.table.columns)
check(p2.table.get_values(p2.table.all_iids()[0])[_legacy_cols.index("region")] == "未分类",
      "旧库账号地区显示为未分类")
# 全部页面仍可正常切换
nav_ok = True
from app.ui.app_window import NAV_ITEMS
for key, _icon, _label in NAV_ITEMS:
    try:
        app2.show_page(key)
        app2.update_idletasks()
    except Exception:  # noqa: BLE001
        nav_ok = False
check(nav_ok, "旧库下 8 个页面均可正常切换")
app2.destroy()

print(f"\n===== 结果：PASS {len(PASS)} / FAIL {len(FAIL)} =====")
for f in FAIL:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
