"""VideoParser 测试：item_list 响应解析、URL 构造、去重、缺失字段、递归兜底。"""
from __future__ import annotations

import json
import unittest

from app.collector.video_parser import VideoParser
from tests.fixtures import make_item, make_item_list, today_items


class TestVideoParser(unittest.TestCase):
    def setUp(self):
        self.parser = VideoParser()

    def test_parse_basic_fields(self):
        body = make_item_list(today_items())
        items = self.parser.parse_item_list(body)
        self.assertEqual(len(items), 4)
        first = items[0]
        self.assertEqual(first.video_id, "7689051423832575252")
        self.assertEqual(first.username, "demo_alpha")
        self.assertEqual(first.raw_publish_time, 1790246798)
        self.assertEqual(first.time_source, "epoch")
        self.assertEqual(first.raw_url,
                         "https://www.tiktok.com/@demo_alpha/video/7689051423832575252")

    def test_create_time_converted_to_date(self):
        # createTime=1790246798 → 北京时间 2026-09-24
        from app.core.date_resolver import DateResolver
        body = make_item_list(today_items())
        items = self.parser.parse_item_list(body)
        r = DateResolver("Asia/Shanghai").resolve(items[0].raw_publish_time)
        self.assertEqual(r.date_str, "2026-09-24")

    def test_empty_body(self):
        self.assertEqual(self.parser.parse_item_list(""), [])
        self.assertEqual(self.parser.parse_item_list(None), [])

    def test_invalid_json(self):
        self.assertEqual(self.parser.parse_item_list("not json"), [])

    def test_dedup_by_video_id(self):
        items = today_items()
        dup = items + [items[0]]  # 第一条重复
        body = make_item_list(dup)
        parsed = self.parser.parse_item_list(body)
        self.assertEqual(len(parsed), 4)  # 去重后仍 4 条

    def test_missing_create_time_kept_but_unconfirmed(self):
        item = make_item("7689999999999999999", None)
        body = make_item_list([item])
        parsed = self.parser.parse_item_list(body)
        self.assertEqual(len(parsed), 1)
        self.assertIsNone(parsed[0].raw_publish_time)
        self.assertEqual(parsed[0].time_source, "none")

    def test_item_list_not_top_level_recursive_fallback(self):
        # 模拟 itemList 藏在嵌套结构里
        nested = {"data": {"result": {"itemList": today_items()}}}
        body = json.dumps(nested)
        parsed = self.parser.parse_item_list(body)
        self.assertEqual(len(parsed), 4)

    def test_order_preserved_descending(self):
        body = make_item_list(today_items())
        times = [i.raw_publish_time for i in self.parser.parse_item_list(body)]
        self.assertEqual(times, sorted(times, reverse=True))


if __name__ == "__main__":
    unittest.main()
