"""采集任务页「按地区选择账号」UI 检查（源码态，无需网络与浏览器）。

验证：
1. 地区筛选下拉存在且含 全部地区 / 越南 / 缅甸 / 未分类
2. 首次进入默认全选（不分类全选）
3. 切到某地区 → 列表只显示该地区账号，且自动勾选该地区全部
4. `_selected_accounts()` 返回的账号与勾选一致（与当前筛选无关）
5. 切回「全部地区」= 不分类全选
6. 手工取消勾选生效；切换地区会按「替换」语义重新勾选
7. 每账号数量在切换地区后不丢失
8. 未勾选任何账号时点采集不会启动
"""
import sys

sys.path.insert(0, r"D:\TikTokLinkCollector")

import tempfile
from pathlib import Path

from app.app import AppServices
from app.core.models import Account
from app.ui.app_window import AppWindow

PASS, FAIL = [], []


def check(cond, msg):
    (PASS if cond else FAIL).append(msg)
    print(("  PASS  " if cond else "  FAIL  ") + msg)


tmp = Path(tempfile.mkdtemp(prefix="collect_region_ui_"))
ctx = AppServices(base_dir=tmp)

DATA = [
    ("vn_1", "越南"), ("vn_2", "越南"), ("vn_3", "越南"),
    ("mm_1", "缅甸"), ("mm_2", "缅甸"),
    ("na_1", ""),
]
for u, region in DATA:
    ctx.db.insert_account(Account(
        account_id=u, username=u, profile_url=f"https://www.tiktok.com/@{u}",
        region=region, display_name=f"昵称{u}"))

app = AppWindow(ctx)
app.geometry("1280x860")
app.show_page("collect")
for _ in range(6):
    app.update_idletasks()
    app.update()

page = app.pages["collect"]

print("\n--- 1) 地区筛选下拉 ---")
opts = list(page._region_filter.cget("values"))
print("  选项:", opts)
for want in ("全部地区", "越南", "缅甸", "未分类"):
    check(want in opts, f"下拉含「{want}」")

print("\n--- 2) 首次默认全选（不分类）---")
check(page._checked_ids == {u for u, _ in DATA},
      f"默认勾选全部 6 个（实得 {sorted(page._checked_ids)}）")
check(len(page._checkboxes) == 6, "列表显示全部 6 个")

print("\n--- 3) 切到「越南」→ 只显示并勾选越南 ---")
page._region_filter.set("越南")
page._on_region_changed()
app.update_idletasks()
check(set(page._checkboxes) == {"vn_1", "vn_2", "vn_3"},
      f"只显示越南账号（实得 {sorted(page._checkboxes)}）")
check(page._checked_ids == {"vn_1", "vn_2", "vn_3"},
      f"自动勾选越南全部（实得 {sorted(page._checked_ids)}）")

print("\n--- 4) 采集集合与勾选一致 ---")
sel = {a.account_id for a in page._selected_accounts()}
check(sel == {"vn_1", "vn_2", "vn_3"}, f"返回越南 3 个（实得 {sorted(sel)}）")

print("\n--- 5) 切到「缅甸」---")
page._region_filter.set("缅甸")
page._on_region_changed()
app.update_idletasks()
check(set(page._checkboxes) == {"mm_1", "mm_2"}, "只显示缅甸账号")
check(page._checked_ids == {"mm_1", "mm_2"}, "自动勾选缅甸全部")
sel2 = {a.account_id for a in page._selected_accounts()}
check(sel2 == {"mm_1", "mm_2"}, f"返回缅甸 2 个（实得 {sorted(sel2)}）")

print("\n--- 6) 切回「全部地区」= 不分类全选 ---")
page._region_filter.set("全部地区")
page._on_region_changed()
app.update_idletasks()
check(len(page._checkboxes) == 6, "显示全部 6 个")
check(len(page._checked_ids) == 6, "勾选全部 6 个（不分类全采）")

print("\n--- 7) 手工取消 + 切换地区（替换语义）---")
page._checkboxes["vn_1"][0].deselect()
page._toggle_checked("vn_1")
check("vn_1" not in page._checked_ids, "手工取消勾选生效")
page._region_filter.set("越南")
page._on_region_changed()
check("vn_1" in page._checked_ids, "切换地区后按该地区重新勾选")

print("\n--- 8) 每账号数量在切换地区后不丢失 ---")
page._checkboxes["vn_2"][1].delete(0, "end")
page._checkboxes["vn_2"][1].insert(0, "9")
page._snapshot_one("vn_2")
page._region_filter.set("缅甸")
page._on_region_changed()
page._region_filter.set("越南")
page._on_region_changed()
app.update_idletasks()
val = page._checkboxes["vn_2"][1].get()
check(val == "9", f"数量输入切换地区后保留（实得 {val!r}）")
counts = {a.account_id: a.collect_count for a in page._selected_accounts()}
check(counts.get("vn_2") == 9, f"_selected_accounts 使用保存的数量（实得 {counts.get('vn_2')}）")

print("\n--- 9) 未勾选账号时不会启动采集 ---")
page._check_all(False)
app.update_idletasks()
check(len(page._checked_ids) == 0, "已清空勾选")
page._start()
check(page._running is False, "未选账号时不启动采集线程")

print("\n--- 10) 地区筛选无匹配时的提示 ---")
empty_dir_page = page
page._region_filter.set("泰国")       # 没有任何泰国账号
page._render_accounts()
app.update_idletasks()
check(len(page._checkboxes) == 0, "无匹配时不渲染任何账号行")

app.destroy()

print(f"\n===== 结果：PASS {len(PASS)} / FAIL {len(FAIL)} =====")
for f in FAIL:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
