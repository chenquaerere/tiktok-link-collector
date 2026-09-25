"""ProfileCollector —— 账号主页作品采集（P10）。

组合 BrowserManager / SessionManager / TikTokProvider / VideoParser，
完成单账号主页作品的流式采集。

关键设计：
- 单账号串行：一次只处理一个账号，采集完（或失败）才进入下一个。
- 数据来源优先网络响应（/api/post/item_list/），不依赖 DOM 相对时间。
- 通过 on_item(item) -> bool 回调把每条作品交给上层（引擎）做日期判定/去重/入库；
  回调返回 False 表示「达到数量或确认无更多目标日期作品」，立即停止本账号。
- 滚动触发 item_list 分页；连续多次滚动无新作品视为「没有更多作品」。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from app.core.models import Account, ParsedVideoItem

from .exceptions import RateLimited

# on_item 回调：返回 True 继续采集，False 停止本账号
ItemCallback = Callable[[ParsedVideoItem], bool]


class ProfileCollector:
    def __init__(
        self,
        browser,
        session,
        provider,
        parser,
        initial_wait_ms: int = 4000,
        scroll_wait_ms: int = 1200,
        max_scrolls: int = 30,
        idle_scrolls_before_stop: int = 4,
    ):
        self.browser = browser
        self.session = session
        self.provider = provider
        self.parser = parser
        self.initial_wait_ms = initial_wait_ms
        self.scroll_wait_ms = scroll_wait_ms
        self.max_scrolls = max_scrolls
        self.idle_scrolls_before_stop = idle_scrolls_before_stop

    def fetch(self, account: Account) -> List[ParsedVideoItem]:
        """满足旧 Fetcher 协议：一次性返回全部解析结果（测试/简单场景用）。"""
        out: List[ParsedVideoItem] = []
        self.collect(account, lambda it: (out.append(it), True)[1])
        return out

    def collect(self, account: Account, on_item: ItemCallback) -> Dict:
        """单账号流式采集。返回诊断 dict。"""
        diag = {
            "found": 0,
            "item_list_requests": 0,
            "scrolls": 0,
            "stopped_by_callback": False,
            "rate_limited": False,
            "create_times": [],  # 记录 createTime 顺序，供排序可靠性诊断
        }

        context = self.browser.new_context(self.session.user_data_dir_for(account))
        try:
            page = self.provider.load_profile(context, account.username)
            self.session.ensure_login(page)  # 登录/验证失效抛 LoginRequired

            # 监听 item_list 网络响应
            queue: List[str] = []

            def on_response(resp):
                try:
                    url = resp.url
                    if "/api/post/item_list/" in url and "json" in resp.headers.get("content-type", ""):
                        if resp.status == 429:
                            diag["rate_limited"] = True
                            return
                        body = resp.text()
                        if body:
                            queue.append(body)
                            diag["item_list_requests"] += 1
                except Exception:
                    pass

            page.on("response", on_response)

            # 等待首次 item_list 请求完成
            page.wait_for_timeout(self.initial_wait_ms)

            emitted_ids = set()
            idle = 0
            for _ in range(self.max_scrolls):
                new_items = 0
                while queue:
                    body = queue.pop(0)
                    for item in self.parser.parse_item_list(body):
                        if not item.video_id or item.video_id in emitted_ids:
                            continue
                        emitted_ids.add(item.video_id)
                        diag["found"] += 1
                        new_items += 1
                        if item.raw_publish_time is not None:
                            diag["create_times"].append(item.raw_publish_time)
                        # 交给上层；False → 停止本账号
                        if not on_item(item):
                            diag["stopped_by_callback"] = True
                            return diag

                # 滚动触发更多 item_list
                try:
                    page.mouse.wheel(0, 2500)
                except Exception:
                    pass
                page.wait_for_timeout(self.scroll_wait_ms)
                diag["scrolls"] += 1

                if new_items == 0:
                    idle += 1
                    if idle >= self.idle_scrolls_before_stop:
                        break  # 连续多次无新作品 → 没有更多
                else:
                    idle = 0

            # 限流检测：一个作品都没采到且命中 429 → 抛退避异常，交由引擎指数退避
            if diag.get("rate_limited") and diag["found"] == 0:
                raise RateLimited("触发 TikTok 限流(HTTP 429)，需退避等待后重试")

            return diag
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
