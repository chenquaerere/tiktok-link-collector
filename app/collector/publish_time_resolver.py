"""PublishTimeResolver —— 作品发布时间解析 + 详情页绝对时间回退（P8/P9）。

数据来源（真实探针验证）：
- 一级：item_list 的 item.createTime（Unix 秒）→ CONFIRMED
- 二级回退：详情页 __UNIVERSAL_DATA_FOR_REHYDRATION__ 的 createTime（值一致）→ CONFIRMED
- 三级：仅有相对时间（"2h ago"/"Yesterday"）→ RELATIVE_ONLY，禁止用于日期判断
- 仍无法确认 → UNCONFIRMED，直接排除（宁可少采不可错采）

职责边界：
- resolve()：输入 ParsedVideoItem（含 raw_publish_time=createTime），委托 core.DateResolver。
- 详情页回退通过导航回调注入，解析逻辑为纯函数（可离线测试）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from app.core.date_resolver import DateResolver, DateResolution
from app.core.models import ParsedVideoItem
from app.collector.video_parser import VideoParser

# 详情页回退回调：输入 (video_url, video_id)，返回 createTime(int) 或 None
DetailFetcher = Callable[[str, str], Optional[int]]


class PublishTimeResolver:
    def __init__(self, resolver: DateResolver, detail_fetcher: Optional[DetailFetcher] = None):
        self.resolver = resolver
        self.detail_fetcher = detail_fetcher

    def resolve(self, item: ParsedVideoItem, page: Any = None) -> DateResolution:
        """解析单条作品发布时间。

        - raw_publish_time 有值（epoch/iso/absolute）→ 直接解析
        - 缺失且提供 page / detail_fetcher → 详情页回退
        - 仍无 → UNCONFIRMED
        """
        raw = item.raw_publish_time
        if raw is not None:
            return self.resolver.resolve(raw)

        # 回退：详情页取绝对 createTime
        ct = self._fallback_create_time(item, page)
        if ct is not None:
            return self.resolver.resolve(ct)

        return self.resolver.resolve(None)

    # ---- 详情页回退 ----
    def _fallback_create_time(self, item: ParsedVideoItem, page: Any) -> Optional[int]:
        # 优先使用注入的 fetcher（ProfileCollector 会注入真实导航实现）
        if self.detail_fetcher is not None and item.video_id:
            return self.detail_fetcher(item.raw_url or "", item.video_id)
        # 否则若拿到 page，直接导航详情页
        if page is not None:
            return self._navigate_and_extract(page, item)
        return None

    @staticmethod
    def _navigate_and_extract(page: Any, item: ParsedVideoItem) -> Optional[int]:
        if not item.raw_url:
            return None
        try:
            page.goto(item.raw_url, wait_until="domcontentloaded", timeout=60000)
            # 等待 SSR 落地
            for _ in range(15):
                page.wait_for_timeout(1000)
                try:
                    if page.evaluate("() => !!(window['__UNIVERSAL_DATA_FOR_REHYDRATION__'] || window['SIGI_STATE'])"):
                        break
                except Exception:
                    pass
            html = page.content()
            return PublishTimeResolver.extract_detail_create_time(html, item.video_id)
        except Exception:
            return None

    @staticmethod
    def extract_detail_create_time(html: str, video_id: str) -> Optional[int]:
        """纯函数：从详情页 HTML 提取目标 video_id 的 createTime。"""
        if not html:
            return None
        m = re.search(r'id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            return None
        for o in VideoParser._find_item_objects(data):
            if str(o.get("id")) == str(video_id):
                ct = o.get("createTime")
                if ct is not None:
                    try:
                        return int(ct)
                    except (TypeError, ValueError):
                        return None
        return None
