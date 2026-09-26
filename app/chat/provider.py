"""ChatProvider —— TikTok 消息页站点访问（聊天模块专用）。

数据来源（真实探针验证，见 docs/CHAT_PROBE_REPORT.md）：
- 会话列表：DOM `[data-e2e="dm-new-conversation-item"]`，元素带 `data-conversation-id`。
- 好友列表：HTTP `GET /api/im/spotlight/relation/` → followings[]（uid/sec_uid/unique_id/nickname）。
- 聊天头部：`[class*="DivChatHeader"]`（好友显示 昵称+@用户名；群聊显示 群名+N members）。
- 共享视频：会话内 `<a href="/@user/video/{id}">`。

设计原则：
- 只读 DOM 与网络响应，不解析二进制 WS 协议。
- 不修改作品采集模块的任何代码；仅复用 BrowserManager/SessionManager 的产物
  （持久化 context 由调用方传入）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.chat.models import ChatCandidate, CHAT_TYPE_GROUP, peer_uid_from_dm_id

MSG_URL = "https://www.tiktok.com/messages"

_CONV_ITEM_SEL = '[data-e2e="dm-new-conversation-item"], [data-conversation-id]'
_CHAT_HEADER_SEL = '[class*="DivChatHeader"]'


class ChatProvider:
    def __init__(self, load_timeout_ms: int = 30000, list_wait_ms: int = 20000):
        self.load_timeout_ms = load_timeout_ms
        self.list_wait_ms = list_wait_ms

    # ---- 页面加载 ----
    def load_messages(self, context: Any):
        """打开消息页并等待会话列表渲染，返回 page。

        会话列表由二进制 WS 推送后前端渲染，需要给足等待时间。
        """
        page = context.new_page()
        page.goto(MSG_URL, wait_until="domcontentloaded", timeout=self.load_timeout_ms)
        try:
            # 一出现会话项就继续（正常 2~5 秒），不再无脑等满
            page.wait_for_selector(_CONV_ITEM_SEL, timeout=self.list_wait_ms)
            page.wait_for_timeout(800)          # 留一点时间给列表稳定
        except Exception:
            page.wait_for_timeout(2000)         # 新号可能真的没有会话
        return page

    # ---- 一次性快照：会话列表 + 好友列表 ----
    def open_messages_snapshot(self, context: Any,
                               on_stage=None,
                               login_check=None,
                               friend_poll_s: int = 6,
                               friend_reload_wait_ms: int = 10000):
        """打开消息页并一次拿到 (page, conversations, friends)。

        相比「load_messages + list_friends(reload)」旧流程快一倍以上：
        1. 进页前就挂好友 API 监听器 → 首屏加载若触发接口则**零额外等待**；
        2. 未触发时先轮询 friend_poll_s 秒（不刷新页面）；
        3. 仍拿不到才 reload 一次（等待时间减半），reload 后重取会话列表。
        login_check: 进页后立即调用的登录态检查（未登录立刻抛 LoginRequired，
        避免白白等 40 秒才报错）。
        """
        def stage(msg: str) -> None:
            if on_stage:
                try:
                    on_stage(msg)
                except Exception:
                    pass

        page = context.new_page()
        bodies, remove = self._attach_friend_capture(page)
        try:
            stage("正在打开消息页…")
            page.goto(MSG_URL, wait_until="domcontentloaded",
                      timeout=self.load_timeout_ms)
            if login_check is not None:
                login_check(page)   # 未登录/验证码 → LoginRequired 快速失败
            try:
                page.wait_for_selector(_CONV_ITEM_SEL, timeout=self.list_wait_ms)
            except Exception:
                pass  # 列表可能为空（新号）
            page.wait_for_timeout(2000)

            stage("正在获取好友资料…")
            friends: List[ChatCandidate] = []
            for _ in range(friend_poll_s * 2):
                friends = self.parse_friend_bodies(bodies)
                if friends:
                    break
                page.wait_for_timeout(500)

            if not friends:
                # 最后手段：reload 一次触发好友接口（等待减半），随后重取会话
                stage("好友接口未触发，刷新页面重试…")
                page.reload(wait_until="domcontentloaded",
                            timeout=self.load_timeout_ms)
                page.wait_for_timeout(friend_reload_wait_ms)
                friends = self.parse_friend_bodies(bodies)

            stage("正在读取会话列表…")
            conversations = self.list_conversations(page)
            return page, conversations, friends
        finally:
            remove()

    # ---- 会话列表 ----
    # 会话项 DOM 结构（2026-09-26 实测，见 diagnostics/chat_evidence）：
    #   昵称：p[class*="PInfoNickname"]
    #   消息/时间：p[class*="PInfoExtract"]（含 SpanInfoTime）
    # ⚠️ 不能用 innerText 第一行当昵称：有未读消息时第一行是角标数字
    #    （曾把好友昵称解析成 "1"，导致采集时目标校验失败、采不到链接）。
    _NICK_SEL = 'p[class*="PInfoNickname"]'
    _EXTRACT_SEL = 'p[class*="PInfoExtract"]'

    _CONV_JS = """(args) => {
      const [nickSel, extractSel] = args;
      const out = [];
      const seen = new Set();
      const items = document.querySelectorAll(
        '[data-e2e="dm-new-conversation-item"], [data-conversation-id]');
      items.forEach(el => {
        // data-conversation-id 可能不在 e2e 会话项自身上，向上找宿主元素
        let cid = el.getAttribute('data-conversation-id') || '';
        let host = el;
        if (!cid) {
          host = el.closest('[data-conversation-id]');
          cid = host ? host.getAttribute('data-conversation-id') : '';
        }
        if (!cid || seen.has(cid)) return;
        seen.add(cid);
        // 昵称/消息元素优先在 e2e 会话项内找（结构最完整），找不到再扩大到宿主
        const scope = el.querySelector(nickSel) ? el : host;
        const nick = scope.querySelector(nickSel);
        const extract = scope.querySelector(extractSel);
        out.push({
          cid,
          name: ((nick && nick.innerText) || '').split('\\n')[0].trim(),
          text: (el.innerText || '').trim(),
          extract: ((extract && extract.innerText) || '').replace(/\\s*\\n\\s*/g, ' ').trim(),
        });
      });
      return out;
    }"""

    def list_conversations(self, page: Any) -> List[ChatCandidate]:
        """抽取当前账号全部会话（好友单聊 + 群聊）。"""
        raw = self._query_conv_items(page)
        out = self._parse_conv_items(raw)
        if not out:
            # 会话列表可能尚未渲染完成，补等一次再取
            page.wait_for_timeout(5000)
            raw = self._query_conv_items(page)
            out = self._parse_conv_items(raw)
        return out

    def _query_conv_items(self, page: Any) -> list:
        try:
            return page.evaluate(self._CONV_JS,
                                 [self._NICK_SEL, self._EXTRACT_SEL]) or []
        except Exception:
            return []

    @staticmethod
    def _parse_conv_items(raw: list) -> List[ChatCandidate]:
        out: List[ChatCandidate] = []
        for it in raw or []:
            cid = it.get("cid") or ""
            name = (it.get("name") or "").strip()
            if not name:
                # 兜底：昵称元素没找到时退回 innerText 首行（可能不准）
                text = (it.get("text") or "").strip()
                name = text.split("\n")[0].strip() if text else ""
            if not name:
                continue
            if ":" in cid:
                # 好友单聊：0:1:<peerUid>:<selfUid>
                peer = peer_uid_from_dm_id(cid)
                out.append(ChatCandidate(
                    chat_type="friend", name=name, uid=peer, conversation_id=cid,
                    subtitle=_conv_subtitle(it.get("extract") or "")))
            else:
                out.append(ChatCandidate(
                    chat_type=CHAT_TYPE_GROUP, name=name, uid=cid, conversation_id=cid,
                    subtitle=_conv_subtitle(it.get("extract") or "")))
        return out

    # ---- 好友列表（HTTP API） ----
    @staticmethod
    def parse_friend_bodies(bodies: List[str]) -> List[ChatCandidate]:
        """解析捕获到的 spotlight/relation 响应体 → 好友候选。"""
        out: List[ChatCandidate] = []
        seen = set()
        for body in bodies:
            try:
                data = json.loads(body)
            except (json.JSONDecodeError, TypeError):
                continue
            for f in data.get("followings") or []:
                uid = str(f.get("uid") or "")
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                out.append(ChatCandidate(
                    chat_type="friend",
                    name=f.get("nickname") or f.get("unique_id") or "",
                    handle=f.get("unique_id") or "",
                    uid=uid,
                    sec_uid=f.get("sec_uid") or "",
                    subtitle=(f.get("signature") or "")[:80]))
        return out

    @staticmethod
    def _attach_friend_capture(page: Any):
        """挂 response 监听器，捕获好友 API 响应体。返回 (bodies, remove_fn)。"""
        bodies: List[str] = []

        def on_response(resp):
            try:
                if "/api/im/spotlight/relation" in resp.url and \
                        "json" in resp.headers.get("content-type", ""):
                    bodies.append(resp.text())
            except Exception:
                pass

        page.on("response", on_response)

        def remove():
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        return bodies, remove

    def list_friends(self, page: Any) -> List[ChatCandidate]:
        """捕获 spotlight/relation 好友列表，返回候选（uid/sec_uid/unique_id/nickname）。

        ⚠️ 该方法会 reload 页面（旧流程，慢）；新流程请用 open_messages_snapshot。
        """
        bodies, remove = self._attach_friend_capture(page)
        try:
            # 触发：刷新页面让前端重新拉取好友列表；接口偶发不触发，最多重试 2 次
            for attempt in range(2):
                page.reload(wait_until="domcontentloaded", timeout=self.load_timeout_ms)
                page.wait_for_timeout(self.list_wait_ms)
                if self.parse_friend_bodies(bodies):
                    break
        finally:
            remove()
        return self.parse_friend_bodies(bodies)

    # ---- 打开会话 / 验证 / 抽取 ----
    def open_conversation(self, page: Any, conversation_id: str) -> bool:
        """点击指定会话项并等聊天面板就绪。SPA 不改 URL。返回是否点击成功。

        ⚠️ 旧实现固定 wait_for_timeout(4000)，每次白等 4 秒；
        改为「等聊天头部出现」（通常 <1 秒），最多等 4 秒。
        """
        sel = f'[data-conversation-id="{_css_escape(conversation_id)}"]'
        try:
            el = page.locator(sel).first
            if el.count() == 0:
                return False
            el.click()
        except Exception:
            return False
        # 条件等待：聊天头部渲染出来即可继续
        try:
            page.wait_for_selector(_CHAT_HEADER_SEL, timeout=4000)
            page.wait_for_timeout(500)
        except Exception:
            page.wait_for_timeout(1500)     # 头部没出来也再给一点时间，交由上层校验拦截
        return True

    def chat_header_text(self, page: Any) -> str:
        """当前打开聊天的头部文本（好友：名+@用户名；群聊：群名+N members）。"""
        try:
            el = page.locator(_CHAT_HEADER_SEL).first
            if el.count() == 0:
                return ""
            return (el.inner_text() or "").strip()
        except Exception:
            return ""

    # ⚠️ 顺序必须按「垂直位置」判定，不能用 DOM 顺序：
    #    聊天记录是自上而下按时间排列（最下面 = 最新分享的视频），
    #    DOM 顺序多为「旧→新」，直接取前 N 条会拿到最旧的 N 条（用户实测反馈）。
    #    getBoundingClientRect().top 越大 = 位置越靠下 = 越新。
    #
    # ⚠️ 作用域必须限定在聊天面板 DivChatBox 内：
    #    整页扫描会把「左侧会话列表的预览卡片」和「页头区域」的隐藏链接
    #    一起抓出来（实测这些隐藏链接全部指向同一个账号的作品），
    #    导致不管选哪个会话都拿到同一批错误链接。
    CHAT_BOX_SEL = '[class*="DivChatBox"]'
    _CARD_SEL = 'div[style*="background-image"]'

    # 分享卡片本身不带 <a>，视频 id 藏在 React props 里
    # （__reactProps$xxx → children.props.itemId），必须从 props 里取。
    _CARDS_JS = """() => {
      const box = document.querySelector('[class*="DivChatBox"]');
      if (!box) return {error: 'chat-box-not-found', cards: []};

      function findItemId(el) {
        for (let depth = 0; depth < 6 && el; depth++) {
          const keys = Object.keys(el).filter(k => k.indexOf('__reactProps') === 0);
          for (const k of keys) {
            let pr = null;
            try { pr = el[k]; } catch (e) { continue; }
            const pools = [pr,
                           pr && pr.children,
                           pr && pr.children && pr.children.props,
                           pr && pr.props];
            for (const p of pools) {
              if (p && typeof p.itemId === 'string' && /^\\d{15,}$/.test(p.itemId)) {
                return p.itemId;
              }
            }
            // 兜底：沿 children 链再找两层
            let node = pr, guard = 0;
            while (node && guard++ < 50) {
              const props = node.props || (node.children && node.children.props);
              if (props && typeof props.itemId === 'string' &&
                  /^\\d{15,}$/.test(props.itemId)) return props.itemId;
              node = node.children || null;
            }
          }
          el = el.parentElement;
        }
        return null;
      }

      const out = [];
      const seen = new Set();
      box.querySelectorAll('div[style*="background-image"]').forEach(d => {
        const itemId = findItemId(d);
        if (!itemId || seen.has(itemId)) return;
        seen.add(itemId);
        const r = d.getBoundingClientRect();
        out.push({item_id: itemId, top: r.top, left: r.left,
                  height: r.height, width: r.width});
      });
      // top 越大 = 越靠下 = 越新
      out.sort((a, b) => b.top - a.top);
      return {cards: out};
    }"""

    def extract_chat_items(self, page: Any) -> List[Dict[str, Any]]:
        """抽取聊天面板内全部「分享卡片」，**按垂直位置 下→上（最新→最旧）** 返回。

        返回 [{"item_id": "7689…", "top": 123.0, "left": …}, …]。
        只有当前已渲染（含虚拟滚动已加载）的卡片会被返回，调用方需滚动加载更多。
        """
        try:
            res = page.evaluate(self._CARDS_JS) or {}
        except Exception:
            return []
        cards = (res or {}).get("cards") or []
        parsed: List[Dict[str, Any]] = []
        for c in cards:
            iid = str(c.get("item_id") or "")
            if not iid:
                continue
            try:
                top = float(c.get("top") or 0.0)
            except (TypeError, ValueError):
                top = 0.0
            parsed.append({"item_id": iid, "top": top,
                           "left": float(c.get("left") or 0.0)})
        # top 越大 = 越靠下 = 越新；同一 itemId 保留最靠下的那次
        parsed.sort(key=lambda x: x["top"], reverse=True)
        out: List[Dict[str, Any]] = []
        seen: set = set()
        for it in parsed:
            if it["item_id"] in seen:
                continue
            seen.add(it["item_id"])
            out.append(it)
        return out

    # ---- 分享内容解析（itemId → 作者 / 类型 / 文案） ----
    _DETAIL_JS = """async (itemId) => {
      try {
        const r = await fetch('/api/im/item_detail/?itemId=' + encodeURIComponent(itemId),
                              {credentials: 'include'});
        const b = await r.json();
        const st = ((b || {}).itemInfo || {}).itemStruct || {};
        const au = st.author || {};
        return {ok: true, status: r.status, code: (b || {}).statusCode,
                id: st.id || '', unique_id: au.uniqueId || '',
                nickname: au.nickname || '', is_photo: !!st.imagePost,
                desc: (st.desc || '').slice(0, 80)};
      } catch (e) { return {ok: false, error: String(e)}; }
    }"""

    def resolve_item(self, page: Any, item_id: str) -> Dict[str, Any]:
        """用 itemId 调站点接口拿作者等信息（带进程内缓存）。"""
        cache = getattr(self, "_detail_cache", None)
        if cache is None:
            cache = self._detail_cache = {}
        if item_id in cache:
            return cache[item_id]
        try:
            res = page.evaluate(self._DETAIL_JS, item_id) or {}
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "error": str(exc)}
        res.setdefault("id", item_id)
        cache[item_id] = res
        return res

    # 批量并发解析：串行 N 条 = N 次网络往返（15 条约 10s+），
    # 分片并发后 3 片左右即可拿完（约 1~2s），明显提速。
    _DETAIL_BATCH_JS = """async (ids) => {
      const one = async (itemId) => {
        try {
          const r = await fetch('/api/im/item_detail/?itemId=' + encodeURIComponent(itemId),
                                {credentials: 'include'});
          const b = await r.json();
          const st = ((b || {}).itemInfo || {}).itemStruct || {};
          const au = st.author || {};
          return {item_id: itemId, ok: true, status: r.status, code: (b || {}).statusCode,
                  id: st.id || '', unique_id: au.uniqueId || '',
                  nickname: au.nickname || '', is_photo: !!st.imagePost,
                  desc: (st.desc || '').slice(0, 80)};
        } catch (e) { return {item_id: itemId, ok: false, error: String(e)}; }
      };
      return await Promise.all(ids.map(one));
    }"""

    def resolve_items(self, page: Any, item_ids: List[str],
                      chunk: int = 6) -> Dict[str, Dict[str, Any]]:
        """批量解析多个 itemId（带缓存）。返回 {item_id: info}。"""
        cache = getattr(self, "_detail_cache", None)
        if cache is None:
            cache = self._detail_cache = {}
        todo = [i for i in item_ids if i and i not in cache]
        for start in range(0, len(todo), max(1, chunk)):
            part = todo[start:start + max(1, chunk)]
            try:
                rows = page.evaluate(self._DETAIL_BATCH_JS, part) or []
            except Exception as exc:  # noqa: BLE001
                rows = [{"item_id": i, "ok": False, "error": str(exc)} for i in part]
            by_id = {str(r.get("item_id") or ""): r for r in rows}
            for i in part:
                res = by_id.get(i) or {"ok": False, "error": "no-response"}
                res.setdefault("id", i)
                cache[i] = res
        return {i: cache.get(i, {"ok": False, "id": i}) for i in item_ids}

    @staticmethod
    def build_item_url(item_id: str, unique_id: str, is_photo: bool = False) -> str:
        """拼真实作品链接：/@作者/video|photo/ID。"""
        kind = "photo" if is_photo else "video"
        author = (unique_id or "").strip() or "i"
        return f"https://www.tiktok.com/@{author}/{kind}/{item_id}"

    def scroll_history(self, page: Any, rounds: int = 10, wait_ms: int = 1500) -> None:
        """在聊天区向上滚动加载历史消息（多轮，直到不再增长由上层判断）。

        ⚠️ 必须先把鼠标移到聊天面板上再滚轮：mouse.wheel 滚动的是指针下的
        元素，默认指针在 (0,0) 会滚到会话侧栏而不是聊天记录。
        """
        try:
            vw = page.viewport_size.get("width", 1366) if page.viewport_size else 1366
            vh = page.viewport_size.get("height", 900) if page.viewport_size else 900
            # 聊天面板在打开会话后位于右半区（左侧是会话列表）
            page.mouse.move(int(vw * 0.72), int(vh * 0.5))
        except Exception:
            pass
        for _ in range(rounds):
            try:
                page.mouse.wheel(0, -3000)
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)


def _conv_subtitle(extract_text: str) -> str:
    """会话项摘要：消息预览元素文本（已含最后消息 + 时间）。"""
    return (extract_text or "").strip()[:80]


def _css_escape(v: str) -> str:
    """CSS 属性选择器值转义（引号与反斜杠）。"""
    return (v or "").replace("\\", "\\\\").replace('"', '\\"')
