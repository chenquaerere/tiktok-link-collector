"""作品链接标准化：统一为 https://www.tiktok.com/@username/video/{video_id}，核心唯一键为 video_id。"""
from __future__ import annotations

import re
from typing import Optional, Tuple
from urllib.parse import urlparse

_TIKTOK_HOST_SUFFIX = "tiktok.com"
_VIDEO_PATH_RE = re.compile(r"^/@([^/]+)/video/(\d+)$", re.I)
_VIDEO_ID_RE = re.compile(r"/video/(\d{8,})", re.I)
_USERNAME_RE = re.compile(r"@([^/?]+)")

# 短链需联网跳转才能拿到 video_id，离线无法解析
_SHORT_HOSTS = {"vm.tiktok.com", "vt.tiktok.com", "m.tiktok.com"}


def normalize_url(raw: str, username_hint: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """返回 (normalized_url, video_id, username)。无法识别时返回 (None, None, None)。"""
    if not raw or not isinstance(raw, str):
        return None, None, None
    s = raw.strip().strip("\"'<>")
    if not s:
        return None, None, None

    # 纯数字：视为 video_id
    if s.isdigit():
        vid = s
        return _build(username_hint or "", vid), vid, (username_hint or "")

    parsed = urlparse(s)
    host = (parsed.hostname or "").lower()

    if not host:
        # 非完整 URL，尝试提取 /video/<id>
        m = _VIDEO_ID_RE.search(s)
        if m:
            vid = m.group(1)
            uname = username_hint or ""
            return _build(uname, vid), vid, uname
        return None, None, None

    if _TIKTOK_HOST_SUFFIX not in host:
        return None, None, None

    if host in _SHORT_HOSTS:
        # 短链：需要联网解析，标记待处理
        return None, None, None

    path = parsed.path.rstrip("/")
    m = _VIDEO_PATH_RE.match(path)
    if m:
        uname, vid = m.group(1), m.group(2)
        return _build(uname, vid), vid, uname

    # 兜底：从路径提取 /video/<id>
    m2 = _VIDEO_ID_RE.search(path)
    if m2:
        vid = m2.group(1)
        uname = username_hint or _extract_username(path)
        return _build(uname, vid), vid, uname

    return None, None, None


def _extract_username(path: str) -> str:
    m = _USERNAME_RE.search(path)
    return m.group(1) if m else ""


def _build(username: str, video_id: str) -> str:
    if username:
        return f"https://www.tiktok.com/@{username}/video/{video_id}"
    return f"https://www.tiktok.com/video/{video_id}"


def canonical_key(video_id: str) -> str:
    """核心唯一标识，始终使用 video_id，而非完整 URL。"""
    return video_id


def extract_video_id(raw: str) -> Optional[str]:
    _, vid, _ = normalize_url(raw)
    return vid
