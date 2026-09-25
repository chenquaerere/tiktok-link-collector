"""临时验证：Treeview 深色样式是否应用于主窗口解释器。"""
import sys
sys.path.insert(0, r"D:\TikTokLinkCollector")

import tempfile
from pathlib import Path

from app.app import AppServices
from app.ui.theme import COLORS
from app.ui.app_window import AppWindow

_tmp = tempfile.mkdtemp(prefix="ui_theme_check_")
app = AppWindow(AppServices(base_dir=Path(_tmp)))
app.update_idletasks()

from tkinter import ttk
style = ttk.Style(app)

bg = style.lookup("Treeview", "background")
fg = style.lookup("Treeview", "foreground")
field = style.lookup("Treeview", "fieldbackground")
head_bg = style.lookup("Treeview.Heading", "background")
sb_bg = style.lookup("Vertical.TScrollbar", "background")

print(f"Treeview.background      = {bg}   (expect {COLORS['surface']})")
print(f"Treeview.foreground      = {fg}   (expect {COLORS['text']})")
print(f"Treeview.fieldbackground = {field} (expect {COLORS['surface']})")
print(f"Heading.background       = {head_bg} (expect {COLORS['surface_alt']})")
print(f"Scrollbar.background     = {sb_bg} (expect {COLORS['surface_alt']})")

ok = (
    bg.lower() == COLORS["surface"].lower()
    and fg.lower() == COLORS["text"].lower()
    and field.lower() == COLORS["surface"].lower()
    and head_bg.lower() == COLORS["surface_alt"].lower()
    and sb_bg.lower() == COLORS["surface_alt"].lower()
)
print("RESULT:", "PASS" if ok else "FAIL")
app.destroy()
sys.exit(0 if ok else 1)
