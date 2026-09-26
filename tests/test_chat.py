"""聊天链接采集模块测试：模型 / 存储 / 搜索 / 解析 / 校验 / 采集（Mock Provider）。"""
from __future__ import annotations

import os
import tempfile
import unittest

from app.chat.collector import ChatLinkCollector
from app.chat.models import (
    CHAT_TYPE_FRIEND,
    CHAT_TYPE_GROUP,
    ChatCandidate,
    ChatTarget,
    extract_video_id,
    is_dm_conversation_id,
    peer_uid_from_dm_id,
)
from app.chat.resolver import ChatTargetResolver
from app.chat.search import ChatSearch
from app.chat.store import ChatStore, target_stable_key
from app.db.database import Database

SELF_UID = "7000000000000000001"
PEER_UID = "7000000000000000002"
DM_CONV = f"0:1:{PEER_UID}:{SELF_UID}"
GROUP_CONV = "7625552426497655056"


def _friend(handle="demo_user", name="Anthony", uid=PEER_UID,
            sec_uid="MS4wLjABAAAA_test", conv=DM_CONV):
    return ChatCandidate(chat_type=CHAT_TYPE_FRIEND, name=name, handle=handle,
                         uid=uid, sec_uid=sec_uid, conversation_id=conv)


def _group(name="TikTok素材交流群", gid=GROUP_CONV):
    return ChatCandidate(chat_type=CHAT_TYPE_GROUP, name=name, uid=gid,
                         conversation_id=gid, subtitle="9 members")


class TestModels(unittest.TestCase):
    def test_dm_id_detection(self):
        self.assertTrue(is_dm_conversation_id(DM_CONV))
        self.assertFalse(is_dm_conversation_id(GROUP_CONV))

    def test_peer_uid_extract(self):
        self.assertEqual(peer_uid_from_dm_id(DM_CONV, SELF_UID), PEER_UID)
        self.assertEqual(peer_uid_from_dm_id(DM_CONV, PEER_UID), SELF_UID)

    def test_video_id_extract(self):
        url = f"https://www.tiktok.com/@{PEER_UID}/video/7688645751874047250"
        self.assertEqual(extract_video_id(url), "7688645751874047250")
        self.assertEqual(extract_video_id("https://example.com/x"), "")

    def test_stable_key_prefers_conversation_id(self):
        self.assertEqual(target_stable_key(ChatTarget(
            chat_type=CHAT_TYPE_GROUP, name="g", conversation_id=GROUP_CONV)),
            f"conv:{GROUP_CONV}")
        self.assertEqual(target_stable_key(ChatTarget(
            chat_type=CHAT_TYPE_FRIEND, name="f", sec_uid="S1")),
            "secuid:S1")


class TestChatSearch(unittest.TestCase):
    def setUp(self):
        self.search = ChatSearch()
        self.friends = [
            _friend(handle="demo_user", name="Anthony", uid="111",
                    sec_uid="S1"),
            _friend(handle="demo_user_02", name="张三", uid="222", sec_uid="S2"),
            _friend(handle="zhangsan", name="张三素材", uid="333", sec_uid="S3"),
        ]
        self.groups = [
            _group(name="TikTok素材交流群", gid="9001"),
            _group(name="TikTok游戏交流群", gid="9002"),
        ]

    def test_handle_exact_first(self):
        out = self.search.search_friends("demo_user", self.friends)
        self.assertTrue(out)
        self.assertEqual(out[0].uid, "111")  # 精确匹配排最前

    def test_at_prefix_normalized(self):
        out = self.search.search_friends("@zhangsan", self.friends)
        self.assertTrue(any(f.uid == "333" for f in out))

    def test_name_fuzzy_multiple(self):
        out = self.search.search_friends("张三", self.friends)
        self.assertEqual(len(out), 2)  # 同名好友全部返回，交由用户选择

    def test_group_name_search(self):
        out = self.search.search_groups("素材交流", self.groups)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].uid, "9001")

    def test_group_no_result(self):
        self.assertEqual(self.search.search_groups("不存在的群", self.groups), [])


class TestResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = ChatTargetResolver()

    def test_build_friend_target_fills_conversation(self):
        friend_no_conv = ChatCandidate(chat_type=CHAT_TYPE_FRIEND, name="FriendA",
                                       handle="demo_friend", uid=PEER_UID, sec_uid="S1",
                                       conversation_id="")
        convs = [ChatCandidate(chat_type=CHAT_TYPE_FRIEND, name="FriendA",
                               conversation_id=DM_CONV, uid=PEER_UID)]
        t = self.resolver.build_target(friend_no_conv, convs, self_uid=SELF_UID)
        self.assertEqual(t.conversation_id, DM_CONV)

    def test_verify_target_friend(self):
        t = ChatTarget(chat_type=CHAT_TYPE_FRIEND, name="FriendA", handle="demo_friend",
                       conversation_id=DM_CONV)
        self.assertTrue(self.resolver.verify_target(t, "FriendA\n\n@demo_friend"))
        self.assertFalse(self.resolver.verify_target(t, "Wrong Name\n\n@other"))

    def test_verify_target_group(self):
        t = ChatTarget(chat_type=CHAT_TYPE_GROUP, name="Nhóm của XoXo",
                       conversation_id=GROUP_CONV)
        self.assertTrue(self.resolver.verify_target(t, "Nhóm của XoXo\n\n9 members"))
        self.assertFalse(self.resolver.verify_target(t, "TikTok游戏交流群\n\n5 members"))

    def test_verify_rejects_empty_header(self):
        t = ChatTarget(chat_type=CHAT_TYPE_GROUP, name="g", conversation_id=GROUP_CONV)
        self.assertFalse(self.resolver.verify_target(t, ""))


class _FakeProvider:
    """Mock Provider：模拟「聊天面板内的分享卡片 → itemId → 作者」链路。

    与真实 Provider 语义一致：
    - extract_chat_items 幂等（读当前已渲染的卡片），每滚动一次多露出若干张；
    - 卡片按 top 降序（下=最新）；
    - resolve_item 把 itemId 解析成作者；
    - 卡片分两列（左=对方分享/低 top 无关，右=自己分享），用于验证筛选逻辑。
    """

    def __init__(self, header, links_per_round, total_links, fail_verify=False,
                 missing_conversation=False, resolve_fail_ids=()):
        self.header = header
        self.links_per_round = links_per_round
        self.total_links = total_links
        self.fail_verify = fail_verify
        self.missing_conversation = missing_conversation
        self.resolve_fail_ids = set(resolve_fail_ids)
        self.scrolls = 0
        self.resolved = []

    def load_messages(self, context):
        return object()

    def open_conversation(self, page, conversation_id):
        return not self.missing_conversation

    def chat_header_text(self, page):
        return self.header

    # 第 i 张卡片：item_id 递增，top 递减（第 0 张在页面最下方 = 最新）
    def extract_chat_items(self, page):
        n = min(self.total_links, (self.scrolls + 1) * self.links_per_round)
        return [{"item_id": f"76000000000000000{i:02d}", "top": 1000.0 - i * 10,
                 "left": 100.0} for i in range(n)]

    def resolve_item(self, page, item_id):
        self.resolved.append(item_id)
        if item_id in self.resolve_fail_ids:
            return {"ok": False, "error": "mock fail"}
        return {"ok": True, "id": item_id, "unique_id": "author1",
                "nickname": "A", "is_photo": False, "desc": ""}

    def resolve_items(self, page, item_ids, chunk=6):
        """批量解析（真实 Provider 用分片并发，这里逐个复用单条逻辑）。"""
        return {i: self.resolve_item(page, i) for i in item_ids}

    @staticmethod
    def build_item_url(item_id, unique_id, is_photo=False):
        kind = "photo" if is_photo else "video"
        return f"https://www.tiktok.com/@{unique_id or 'i'}/{kind}/{item_id}"

    def scroll_history(self, page, rounds=1, wait_ms=0):
        self.scrolls += 1


class TestCollector(unittest.TestCase):
    def _target(self):
        return ChatTarget(chat_type=CHAT_TYPE_GROUP, name="TikTok素材交流群",
                          conversation_id=GROUP_CONV)

    def test_collect_completed(self):
        p = _FakeProvider("TikTok素材交流群\n\n9 members", links_per_round=5,
                          total_links=20)
        c = ChatLinkCollector(p, scroll_rounds=10, scroll_wait_ms=0)
        r = c.collect(object(), self._target(), 8)
        self.assertEqual(r.status, "completed")
        self.assertEqual(len(r.links), 8)
        self.assertEqual(r.links[0].order, 0)
        self.assertTrue(r.diagnostics["verified"])

    def test_collect_takes_newest_first(self):
        """取到的必须是「最下面（最新）」的 N 条：第 0 张卡片 top 最大。"""
        p = _FakeProvider("TikTok素材交流群\n\n9 members", links_per_round=5,
                          total_links=20)
        c = ChatLinkCollector(p, scroll_rounds=10, scroll_wait_ms=0)
        r = c.collect(object(), self._target(), 3)
        self.assertEqual(
            [it.video_url for it in r.links],
            [f"https://www.tiktok.com/@author1/video/76000000000000000{i:02d}"
             for i in range(3)])

    def test_collect_stops_resolving_after_enough(self):
        """拿够数量后不再浪费请求解析更旧的卡片。"""
        p = _FakeProvider("TikTok素材交流群\n\n9 members", links_per_round=10,
                          total_links=30)
        c = ChatLinkCollector(p, scroll_rounds=10, scroll_wait_ms=0)
        r = c.collect(object(), self._target(), 4)
        self.assertEqual(len(r.links), 4)
        self.assertLessEqual(len(p.resolved), 6, "不该把整屏卡片全部解析")

    def test_collect_skips_failed_resolution(self):
        """个别卡片详情解析失败应跳过，不影响其它链接。"""
        p = _FakeProvider("TikTok素材交流群\n\n9 members", links_per_round=5,
                          total_links=10, resolve_fail_ids={"7600000000000000000"})
        c = ChatLinkCollector(p, scroll_rounds=6, scroll_wait_ms=0)
        r = c.collect(object(), self._target(), 4)
        self.assertGreaterEqual(len(r.links), 4)
        self.assertNotIn("7600000000000000000",
                         [it.video_id for it in r.links])

    def test_stop_event_returns_stopped(self):
        """停止信号置位后必须尽快返回 status=stopped，且保留已采到的链接。"""
        import threading
        from app.chat.collector import ChatLinkCollector
        p = _FakeProvider("TikTok素材交流群\n\n9 members", links_per_round=2,
                          total_links=20)
        c = ChatLinkCollector(p, scroll_rounds=10, scroll_wait_ms=0)
        ev = threading.Event()
        ev.set()                       # 一开始就要求停止
        r = c.collect(object(), self._target(), 8, stop_event=ev)
        self.assertEqual(r.status, "stopped")
        self.assertIn("停止", r.error)

    def test_ratio_callback_progresses(self):
        """进度回调必须单调递增，最终达到 1.0（用于驱动进度条）。"""
        from app.chat.collector import ChatLinkCollector
        p = _FakeProvider("TikTok素材交流群\n\n9 members", links_per_round=5,
                          total_links=20)
        c = ChatLinkCollector(p, scroll_rounds=10, scroll_wait_ms=0)
        seen = []
        r = c.collect(object(), self._target(), 5, on_ratio=seen.append)
        self.assertEqual(r.status, "completed")
        self.assertTrue(seen)
        self.assertEqual(seen, sorted(seen))          # 单调不减
        self.assertAlmostEqual(seen[-1], 1.0, places=3)

    def test_batch_resolve_used(self):
        """采集走批量解析接口（而不是逐条解析）。"""
        from app.chat.collector import ChatLinkCollector
        calls = {"batch": 0, "single": 0}

        class P(_FakeProvider):
            def resolve_items(self, page, item_ids, chunk=6):
                calls["batch"] += 1
                return super().resolve_items(page, item_ids, chunk)

            def resolve_item(self, page, item_id):
                calls["single"] += 1
                return super().resolve_item(page, item_id)

        p = P("TikTok素材交流群\n\n9 members", links_per_round=10, total_links=30)
        c = ChatLinkCollector(p, scroll_rounds=5, scroll_wait_ms=0)
        r = c.collect(object(), self._target(), 6)
        self.assertEqual(len(r.links), 6)
        self.assertGreaterEqual(calls["batch"], 1)
        self.assertLess(calls["single"], 12, "不应退化为逐条解析")

    def test_collect_verify_fail_stops(self):
        p = _FakeProvider("TikTok游戏交流群\n\n5 members", links_per_round=5,
                          total_links=20)
        c = ChatLinkCollector(p)
        r = c.collect(object(), self._target(), 8)
        self.assertEqual(r.status, "failed")
        self.assertIn("目标校验失败", r.error)
        self.assertEqual(len(r.links), 0)  # 绝不采错误聊天的链接

    def test_collect_missing_conversation(self):
        p = _FakeProvider("x", 5, 20, missing_conversation=True)
        c = ChatLinkCollector(p)
        r = c.collect(object(), self._target(), 8)
        self.assertEqual(r.status, "failed")
        self.assertIn("找不到目标聊天", r.error)

    def test_collect_no_conversation_id(self):
        p = _FakeProvider("g\n\n9 members", 5, 20)
        c = ChatLinkCollector(p)
        t = ChatTarget(chat_type=CHAT_TYPE_GROUP, name="g", conversation_id="")
        r = c.collect(object(), t, 8)
        self.assertEqual(r.status, "failed")

    def test_collect_partial(self):
        p = _FakeProvider("TikTok素材交流群\n\n9 members", links_per_round=2,
                          total_links=3)
        c = ChatLinkCollector(p, scroll_rounds=5, scroll_wait_ms=0)
        r = c.collect(object(), self._target(), 10)
        self.assertEqual(r.status, "partial")
        self.assertEqual(len(r.links), 3)


class TestChatStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmp, "test.db"))
        self.store = ChatStore(self.db)

    def tearDown(self):
        self.db.close()

    def test_recent_targets(self):
        t = ChatTarget(chat_type=CHAT_TYPE_GROUP, name="TikTok素材交流群",
                       conversation_id=GROUP_CONV, uid=GROUP_CONV)
        self.store.upsert_target(t)
        recents = self.store.recent_targets()
        self.assertEqual(len(recents), 1)
        self.assertEqual(recents[0].conversation_id, GROUP_CONV)
        self.assertEqual(recents[0].name, "TikTok素材交流群")

    def test_replace_links(self):
        t = ChatTarget(chat_type=CHAT_TYPE_FRIEND, name="FriendA", handle="demo_friend",
                       conversation_id=DM_CONV)
        key = target_stable_key(t)
        urls1 = [f"https://www.tiktok.com/@u/video/76000000000000000{i}" for i in range(3)]
        self.store.replace_links(key, urls1)
        self.assertEqual(len(self.store.links_for(key)), 3)
        # 替换式：重新采集按最后一次替换
        urls2 = urls1[:1]
        self.store.replace_links(key, urls2)
        self.assertEqual(self.store.links_for(key), urls2)

    def test_chat_tables_created_without_version_bump(self):
        # SCHEMA_VERSION 保持 2，聊天表靠 IF NOT EXISTS 追加
        self.assertEqual(self.db.query_one("PRAGMA user_version")[0], 2)
        names = self.db.table_names()
        self.assertIn("chat_targets", names)
        self.assertIn("chat_links", names)


if __name__ == "__main__":
    unittest.main()


# ============ 彩色 emoji 渲染 + 好友信息合并（v1.1 补充） ============

class TestEmojiUtil:
    """app/ui/emoji.py —— tkinter 不支持彩色 emoji，用 Pillow 渲染成图。"""

    def test_contains_emoji(self):
        from app.ui.emoji import contains_emoji
        assert contains_emoji("\U0001F525\u26A1") is True          # 🔥⚡️
        assert contains_emoji("UserA\U0001F525") is True
        assert contains_emoji("TikTok素材交流群") is False
        assert contains_emoji("") is False

    def test_emoji_tokens(self):
        from app.ui.emoji import emoji_tokens
        toks = emoji_tokens("ab\U0001F525\u26A1cd")
        assert toks == ["\U0001F525\u26A1"]

    def test_strip_emoji(self):
        from app.ui.emoji import strip_emoji
        assert strip_emoji("UserA\U0001F525") == "UserA"
        assert strip_emoji("\U0001F525\u26A1") == ""

    def test_render_color_image(self):
        """渲染结果必须是彩色（>10 种颜色），且尺寸正确。"""
        from app.ui.emoji import render_emoji_image
        img = render_emoji_image("\U0001F525", 20)
        assert img is not None
        assert img.height == 20
        colors = img.getcolors(100000)
        assert colors and len(colors) > 10  # 黑白渲染只有个位数颜色

    def test_render_failure_returns_none(self):
        from app.ui.emoji import render_emoji_image
        assert render_emoji_image("", 20) is None
        assert render_emoji_image("普通文本", 20) is None  # 非 emoji 渲染不出有效图


class TestMergeFriendInfo:
    """merge_friend_info —— 会话列表好友项用 API 数据补齐 handle/sec_uid。"""

    def _mk(self, **kw):
        return ChatCandidate(**kw)

    def test_merge_by_uid(self):
        from app.chat.models import merge_friend_info
        convs = [self._mk(chat_type="friend", name="张三", uid="7001",
                          conversation_id="0:1:7001:9001")]
        friends = [self._mk(chat_type="friend", name="张三", uid="7001",
                            handle="zhangsan", sec_uid="SEC1")]
        n = merge_friend_info(convs, friends)
        assert n == 1
        assert convs[0].handle == "zhangsan"
        assert convs[0].sec_uid == "SEC1"

    def test_merge_keeps_existing(self):
        from app.chat.models import merge_friend_info
        convs = [self._mk(chat_type="friend", name="李四", uid="7002",
                          conversation_id="0:1:7002:9001", handle="lisi_orig")]
        friends = [self._mk(chat_type="friend", name="李四", uid="7002",
                            handle="lisi_new", sec_uid="SEC2")]
        merge_friend_info(convs, friends)
        assert convs[0].handle == "lisi_orig"  # 不覆盖已有值

    def test_merge_group_untouched(self):
        from app.chat.models import merge_friend_info
        convs = [self._mk(chat_type="group", name="素材群", uid="123",
                          conversation_id="123")]
        friends = [self._mk(chat_type="friend", name="王五", uid="123",
                            handle="wangwu")]
        n = merge_friend_info(convs, friends)
        assert n == 0
        assert convs[0].handle == ""


class TestChatPanelScoping(unittest.TestCase):
    """抽取必须限定在聊天面板内、并按垂直位置排序（下=最新）。

    这是用户实测 bug 的回归测试：旧实现整页扫 a[href*=/video/]，
    抓到的是左侧会话列表预览/页头里的隐藏链接（恒为同一账号的作品），
    导致「不管选群聊还是好友，拿到的都是同一批错误链接」。
    """

    class _Page:
        def __init__(self, payload):
            self._payload = payload
            self.scripts = []

        def evaluate(self, script, arg=None):
            self.scripts.append(script)
            return self._payload

    def test_js_is_scoped_to_chat_box(self):
        from app.chat.provider import ChatProvider
        js = ChatProvider._CARDS_JS
        assert "DivChatBox" in js, "必须在聊天面板 DivChatBox 内取卡片"
        assert "querySelector('[class*=\"DivChatBox\"]')" in js
        assert "document.querySelectorAll('a[href" not in js, "不得再整页扫链接"

    def test_js_reads_itemid_from_react_props(self):
        from app.chat.provider import ChatProvider
        js = ChatProvider._CARDS_JS
        assert "__reactProps" in js, "视频 ID 只存在于 React props 里"
        assert "itemId" in js

    def test_cards_sorted_bottom_up(self):
        from app.chat.provider import ChatProvider
        page = self._Page({"cards": [
            {"item_id": "7600000000000000001", "top": -600, "left": 10},
            {"item_id": "7600000000000000003", "top": 500, "left": 10},
            {"item_id": "7600000000000000002", "top": 0, "left": 10},
        ]})
        items = ChatProvider().extract_chat_items(page)
        assert [it["item_id"] for it in items] == [
            "7600000000000000003", "7600000000000000002", "7600000000000000001"]

    def test_extract_dedupes_and_tolerates_error(self):
        from app.chat.provider import ChatProvider
        page = self._Page({"cards": [
            {"item_id": "7600000000000000001", "top": 1},
            {"item_id": "7600000000000000001", "top": 2},
            {"item_id": "", "top": 3},
        ]})
        items = ChatProvider().extract_chat_items(page)
        assert len(items) == 1

        class BadPage:
            def evaluate(self, script, arg=None):
                raise RuntimeError("dom gone")
        assert ChatProvider().extract_chat_items(BadPage()) == []

    def test_build_item_url(self):
        from app.chat.provider import ChatProvider
        assert ChatProvider.build_item_url("123456789012345", "alice") == \
            "https://www.tiktok.com/@alice/video/123456789012345"
        assert ChatProvider.build_item_url("123456789012345", "alice", True) == \
            "https://www.tiktok.com/@alice/photo/123456789012345"
        # 作者缺失时也要给出可用链接
        assert ChatProvider.build_item_url("123456789012345", "") == \
            "https://www.tiktok.com/@i/video/123456789012345"

    def test_resolve_item_caches(self):
        from app.chat.provider import ChatProvider
        calls = {"n": 0}

        class P:
            def evaluate(self, script, arg=None):
                calls["n"] += 1
                return {"ok": True, "id": arg, "unique_id": "u", "is_photo": False}

        prov = ChatProvider()
        a = prov.resolve_item(P(), "7600000000000000001")
        b = prov.resolve_item(P(), "7600000000000000001")
        assert a == b and calls["n"] == 1, "同一 itemId 只解析一次"


class TestClearLinksInline(unittest.TestCase):
    """结果页「清空链接」改为内联二次确认（不再依赖模态弹窗）。"""

    def test_source_has_no_modal_confirm(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        src = (root / "app/ui/pages/results_page.py").read_text(encoding="utf-8")
        body = src.split("def _clear_links")[1].split("def _disarm_clear")[0]
        assert "self.confirm(" not in body, "清空链接不应再使用模态确认框"
        assert "_clear_armed" in body, "应有内联二次确认状态"

    def test_chat_page_start_has_no_modal_confirm(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        src = (root / "app/ui/pages/chat_page.py").read_text(encoding="utf-8")
        body = src.split("def _start")[1].split("def _collect_worker")[0]
        assert "self.confirm(" not in body, "开始采集不应再弹模态确认框"
        assert "self._thread.start()" in body, "应直接启动采集线程"

    def test_chat_row_is_fully_clickable(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        src = (root / "app/ui/pages/chat_page.py").read_text(encoding="utf-8")
        assert "_bind_row_click" in src, "会话行必须整行可点"
        assert "_highlight_selected" in src, "选中行必须有高亮"
