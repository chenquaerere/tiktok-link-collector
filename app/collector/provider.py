"""TikTokProvider —— TikTok 站点访问（P5）。

- 构造主页 URL：https://www.tiktok.com/@<username>
- 打开主页并等待 SSR（__UNIVERSAL_DATA_FOR_REHYDRATION__ / SIGI_STATE）落地。
- 返回已稳定的 page，供 ProfileCollector 监听网络响应 + 滚动。
- 不依赖固定 CSS 选择器（作品数据来自网络响应）。
"""
from __future__ import annotations

import time
from typing import Any


class TikTokProvider:
    def __init__(self, load_timeout_ms: int = 30000, ssr_wait_seconds: int = 25):
        self.load_timeout_ms = load_timeout_ms
        self.ssr_wait_seconds = ssr_wait_seconds

    def profile_url(self, username: str) -> str:
        return f"https://www.tiktok.com/@{username}"

    def load_profile(self, context: Any, username: str, on_response: Any = None):
        """加载账号主页，返回已稳定的 page。

        ⚠️ **on_response 必须在 `page.goto` 之前注册**（由本方法负责）：
        首屏的 `/api/post/item_list/` 响应就是**最新一批作品**，它可能在页面导航后
        极短时间内（有缓存时甚至 <1s）就返回。若调用方等 load_profile 返回后才
        `page.on("response", …)`，这批响应会被静默丢掉，采集器只能捡到滚动后加载的
        **更旧作品** —— 表现为「拿到的不是最新」「数量对不上」（2026-09-27 实测踩坑：
        同一账号连采两次，第二次整批拿到了几天前的作品）。
        """
        page = context.new_page()
        if on_response is not None:
            page.on("response", on_response)
        page.goto(self.profile_url(username), wait_until="domcontentloaded",
                  timeout=self.load_timeout_ms)
        self._wait_ssr(page)
        return page

    def _wait_ssr(self, page: Any) -> None:
        """等待 SSR 状态落地（作品数据由后续 item_list 异步加载）。"""
        for _ in range(self.ssr_wait_seconds):
            page.wait_for_timeout(1000)
            try:
                ready = page.evaluate(
                    "() => !!(window['__UNIVERSAL_DATA_FOR_REHYDRATION__'] || window['SIGI_STATE'])"
                )
            except Exception:
                ready = False
            if ready:
                return
