"""URL 标准化单元测试。"""
from __future__ import annotations

import unittest

from app.core.url_normalizer import canonical_key, extract_video_id, normalize_url


class TestUrlNormalizer(unittest.TestCase):
    def test_full_url_with_params(self):
        url, vid, uname = normalize_url(
            "https://www.tiktok.com/@alice/video/7351234567890?is_from_webapp=1&sender_device=pc"
        )
        self.assertEqual(url, "https://www.tiktok.com/@alice/video/7351234567890")
        self.assertEqual(vid, "7351234567890")
        self.assertEqual(uname, "alice")

    def test_trailing_slash(self):
        url, vid, _ = normalize_url("https://www.tiktok.com/@bob/video/1234567890123456789/")
        self.assertEqual(vid, "1234567890123456789")

    def test_pure_video_id(self):
        url, vid, _ = normalize_url("7351234567890")
        self.assertEqual(vid, "7351234567890")

    def test_short_link_needs_resolution(self):
        url, vid, _ = normalize_url("https://vm.tiktok.com/abc123/")
        self.assertIsNone(url)
        self.assertIsNone(vid)

    def test_non_tiktok_ignored(self):
        self.assertIsNone(normalize_url("https://example.com/video/123")[1])

    def test_canonical_key_uses_video_id(self):
        self.assertEqual(canonical_key("7351234567890"), "7351234567890")

    def test_extract_video_id(self):
        self.assertEqual(extract_video_id("https://www.tiktok.com/@a/video/7351234567890"), "7351234567890")

    def test_garbage_returns_none(self):
        self.assertEqual(normalize_url("hello world"), (None, None, None))


if __name__ == "__main__":
    unittest.main()
