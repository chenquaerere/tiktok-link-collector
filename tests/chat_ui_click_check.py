"""聊天页点击链路检查：整行点选 → 开始采集（用桩服务，不启动浏览器）。

覆盖用户实际路径：
  1) 注入会话候选 → 渲染列表
  2) 在「行」和「行内子控件」上分别模拟 <Button-1> → 必须选中目标
  3) 模拟「开始采集」→ 必须真正调用到 ChatService.collect（含目标/数量）

用法：python tests/chat_ui_click_check.py
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, r"D:\TikTokLinkCollector")

from app.app import AppServices
from app.ui.app_window import AppWindow
from app.chat.models import CHAT_TYPE_FRIEND, CHAT_TYPE_GROUP, ChatCandidate

errors = []
_tmp = tempfile.mkdtemp(prefix="chat_click_")
ctx = AppServices(base_dir=Path(_tmp))
app = AppWindow(ctx)
app.geometry("1280x800")


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        errors.append(msg)


# 注入账号（否则 _current_account 返回 None）
from app.core.models import Account
ctx.db.insert_account(Account(account_id="demo_user",
                              username="demo_user",
                              profile_url="https://www.tiktok.com/@demo_user"))

app.show_page("chat")
for _ in range(4):
    app.update()
page = app.pages["chat"]
page._account_menu.configure(values=["@demo_user"])
page._account_menu.set("@demo_user")

# ---- 1) 注入候选并渲染 ----
convs = [
    ChatCandidate(chat_type=CHAT_TYPE_GROUP, name="🔥⚡️", uid="7000000000000000003",
                  conversation_id="7000000000000000003", subtitle="Shared a video 14:20"),
    ChatCandidate(chat_type=CHAT_TYPE_FRIEND, name="FriendA", handle="friend_a",
                  uid="7000000000000000004",
                  conversation_id="0:1:7000000000000000004:7000000000000000001",
                  subtitle="Shared a video 11:59"),
]
page._convs = convs
page._refresh_results()
for _ in range(3):
    app.update()
check(len(page._row_frames) == 2, f"渲染 2 行（实际 {len(page._row_frames)}）")

# ---- 2) 点击「行内子控件」（模拟用户点名称，而非小圆圈）----
rows = list(page._row_frames.items())
key0, row0 = rows[0]
labels = [w for w in page._descendants(row0) if w.winfo_class() in ("Frame", "Label")]
clicked = False
for w in labels:
    try:
        w.event_generate("<Button-1>", x=2, y=2)
        app.update()
        if page._selected is not None:
            clicked = True
            print(f"  点击子控件 {w.winfo_class()} 后已选中: {page._selected.name}")
            break
    except Exception as exc:  # noqa: BLE001
        print("   点击异常:", exc)
check(clicked, "点击行内子控件（非圆圈）能选中目标")
check(page._selected is not None and page._selected.name == "🔥⚡️",
      f"选中目标正确（实际 {page._selected.name if page._selected else None}）")
check(page._result_var.get() == key0, "单选钮状态同步")
check(row0.cget("fg_color") != "transparent", "选中行有高亮")

# ---- 3) 直接点整行容器（真实点击落在 CTk 控件的内部 canvas 上）----
page._selected = None
page._highlight_selected("__none__")
row0._canvas.event_generate("<Button-1>", x=120, y=8)
app.update()
check(page._selected is not None, "直接点整行空白区也能选中")

# ---- 4) 开始采集必须真正调用到服务 ----
calls = {}


class _StubService:
    def collect(self, account, target, count, on_progress=None, stop_event=None,
                on_ratio=None):
        calls["account"] = account.username
        calls["target"] = target
        calls["count"] = count
        calls["stop_event"] = stop_event
        if on_progress:
            on_progress("桩：正在读取聊天记录… 已找到 3/5 条")
        if on_ratio:
            on_ratio(0.6)
        from app.chat.models import ChatCollectResult, ChatLinkItem
        r = ChatCollectResult(target=target, requested_count=count, status="completed")
        r.links = [ChatLinkItem(video_url=f"https://www.tiktok.com/@u/video/10000000000000{i:04d}",
                                video_id=str(i), order=i) for i in range(3)]
        return r


page.ctx.build_chat_service = lambda: _StubService()
page._count_entry.delete(0, "end")
page._count_entry.insert(0, "5")
page._start()
# 等 worker 线程 + after 回调把结果回填到界面
deadline = time.time() + 8
while time.time() < deadline and not page._links:
    app.update()
    time.sleep(0.05)
app.update()

check(calls.get("account") == "demo_user", f"服务收到账号（实际 {calls.get('account')}）")
check(getattr(calls.get("target"), "conversation_id", "") == "7000000000000000003",
      "服务收到正确会话标识")
check(calls.get("count") == 5, f"服务收到采集数量 5（实际 {calls.get('count')}）")
check(len(page._links) == 3, f"链接已回填到界面（实际 {len(page._links)}）")
check(page._links_box.get("1.0", "end").strip().count("https://") == 3, "链接框内容正确")

# ---- 5) 清空（内联，不弹窗）----
page._clear_links()
app.update()
check(page._links == [], "清空后内存链接为空")
check(page._links_box.get("1.0", "end").strip() == "", "清空后链接框为空")

app.destroy()
print("\nRESULT:", "PASS" if not errors else f"FAIL {errors}")
sys.exit(0 if not errors else 1)
