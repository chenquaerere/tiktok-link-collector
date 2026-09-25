"""全窗口冒烟测试：实例化主窗口、遍历 7 个页面、触发渲染与 Toast。"""
import sys
sys.path.insert(0, r"D:\TikTokLinkCollector")

import tempfile
from pathlib import Path

from app.app import AppServices
from app.ui.app_window import AppWindow, NAV_ITEMS

_tmp = tempfile.mkdtemp(prefix="ui_smoke_")
ctx = AppServices(base_dir=Path(_tmp))
app = AppWindow(ctx)

errors = []

# 遍历所有页面
for key, icon, label in NAV_ITEMS:
    try:
        app.show_page(key)
        app.update_idletasks()
        app.update()
    except Exception as e:
        errors.append(f"{key}: {e!r}")
    print(f"page {key:10s} OK")

# Toast 冒烟
try:
    app.notify("冒烟测试：这是一条 Toast", title="测试", level="success")
    app.update_idletasks()
    print("toast OK")
except Exception as e:
    errors.append(f"toast: {e!r}")

# 对话框冒烟（不弹窗，仅构造）
from app.ui.components import confirm, EmptyState, LoadingState, StatusBadge, PageHeader
try:
    EmptyState(app.content, title="t", subtitle="s")
    LoadingState(app.content, text="加载中")
    PageHeader(app.content, "h", "sub")
    StatusBadge(app.content, "completed")
    print("components OK")
except Exception as e:
    errors.append(f"components: {e!r}")

app.destroy()

if errors:
    print("\nERRORS:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("RESULT: PASS")
sys.exit(0)
