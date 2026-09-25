"""PublishTimeResolver 测试：createTime→日期、时区、详情页回退、RELATIVE/UNCONFIRMED 排除。"""
from __future__ import annotations

import json
import unittest

from app.collector.publish_time_resolver import PublishTimeResolver
from app.collector.video_parser import VideoParser
from app.core.date_resolver import DateResolver
from app.core.models import DateConfidence, ParsedVideoItem
from tests.fixtures import make_item, make_item_list


def _item(video_id, create_time=None, time_source="epoch"):
    item = ParsedVideoItem(
        video_id=video_id,
        username="demo_alpha",
        raw_url=f"https://www.tiktok.com/@demo_alpha/video/{video_id}",
        raw_publish_time=create_time,
        time_source=time_source,
    )
    return item


class TestPublishTimeResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = PublishTimeResolver(DateResolver("Asia/Shanghai"))

    def test_epoch_to_date(self):
        r = self.resolver.resolve(_item("1", 1790246798))
        self.assertEqual(r.confidence, DateConfidence.CONFIRMED.value)
        self.assertEqual(r.date_str, "2026-09-24")
        self.assertEqual(r.datetime_str, "2026-09-24 18:46:38")

    def test_timezone_conversion(self):
        # 同一 epoch 在不同时区日期不同
        tokyo = PublishTimeResolver(DateResolver("Asia/Tokyo"))
        r = tokyo.resolve(_item("1", 1790246798))
        # 1790246798 = UTC 10:46:38 → 东京 19:46:38 仍是 09-24
        self.assertEqual(r.date_str, "2026-09-24")
        self.assertEqual(r.datetime_str, "2026-09-24 19:46:38")

    def test_target_date_match(self):
        r = self.resolver.resolve(_item("1", 1790246798))
        self.assertTrue(r.matches_date("2026-09-24"))
        self.assertFalse(r.matches_date("2026-09-23"))

    def test_yesterday_epoch_excluded(self):
        r = self.resolver.resolve(_item("2", 1790161614))  # 09-23
        self.assertEqual(r.date_str, "2026-09-23")
        self.assertFalse(r.matches_date("2026-09-24"))

    def test_relative_only_not_confirmed(self):
        item = _item("3", "2h ago", time_source="relative")
        r = self.resolver.resolve(item)
        self.assertEqual(r.confidence, DateConfidence.RELATIVE_ONLY.value)
        self.assertFalse(r.is_confirmed)

    def test_none_unconfirmed_without_detail(self):
        item = _item("4", None)
        r = self.resolver.resolve(item)
        self.assertEqual(r.confidence, DateConfidence.UNCONFIRMED.value)

    def test_detail_fallback_via_fetcher(self):
        # 注入 fetcher：详情页返回绝对 createTime
        def fetcher(url, vid):
            return 1790246798
        resolver = PublishTimeResolver(DateResolver("Asia/Shanghai"), detail_fetcher=fetcher)
        r = resolver.resolve(_item("5", None))
        self.assertEqual(r.confidence, DateConfidence.CONFIRMED.value)
        self.assertEqual(r.date_str, "2026-09-24")

    def test_detail_fallback_returns_none_still_unconfirmed(self):
        def fetcher(url, vid):
            return None
        resolver = PublishTimeResolver(DateResolver("Asia/Shanghai"), detail_fetcher=fetcher)
        r = resolver.resolve(_item("6", None))
        self.assertEqual(r.confidence, DateConfidence.UNCONFIRMED.value)

    def test_extract_detail_create_time_pure(self):
        # 构造详情页 HTML 片段（含 universal data + createTime）
        universal = {
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {
                    "itemInfo": {
                        "itemStruct": {
                            "id": "7689051423832575252",
                            "createTime": 1790246798,
                        }
                    }
                }
            }
        }
        html = ('<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
                + json.dumps(universal) + "</script></html>")
        ct = PublishTimeResolver.extract_detail_create_time(html, "7689051423832575252")
        self.assertEqual(ct, 1790246798)

    def test_extract_detail_missing_returns_none(self):
        self.assertIsNone(PublishTimeResolver.extract_detail_create_time("", "1"))
        self.assertIsNone(PublishTimeResolver.extract_detail_create_time("<html></html>", "1"))


if __name__ == "__main__":
    unittest.main()
