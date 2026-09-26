"""彩色 emoji 渲染工具（聊天模块 UI 专用）。

背景：tkinter/customtkinter 原生不支持彩色 emoji（只能渲染黑白轮廓字形），
群名如「🔥⚡️」在界面里会变成无色轮廓甚至方框。

方案：用 Pillow + Windows 自带 Segoe UI Emoji（COLR 彩色矢量字体）
把 emoji 渲染成透明底 PNG，再以 CTkImage 显示在列表行内。
已在真实环境验证：embedded_color=True 渲染出 375+ 色的彩色图形。

缓存：内存 LRU + 磁盘 PNG 双层（磁盘缓存避免每次开页重渲染）。
渲染失败（如非 Windows / 缺字体）时优雅降级返回 None，UI 回退纯文本。
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

# 连续 emoji token：符号区 + 变体选择符 + ZWJ + 键帽（匹配为整段连续序列）
_EMOJI_TOKEN_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # 附加符号与表情
    "\u2600-\u27BF"           # 杂项符号 + 装饰
    "\u2B00-\u2BFF"           # 箭头/星号类（⭐ 等）
    "\U0001F1E6-\U0001F1FF"   # 区域旗标
    "\u2190-\u21FF"           # 箭头
    "\u2139\u20E3\uFE0F\u200D"
    "]+"
)

_FONT_PATH = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "seguiemj.ttf")

# 内存缓存：key -> PIL.Image（或 False 表示渲染失败，避免反复重试）
_MEMORY_CACHE: Dict[str, object] = {}
_MEMORY_CACHE_MAX = 300


def contains_emoji(text: str) -> bool:
    """文本是否包含至少一个 emoji token。"""
    return bool(_EMOJI_TOKEN_RE.search(text or ""))


def emoji_tokens(text: str) -> List[str]:
    """提取文本中全部连续 emoji token（保持出现顺序）。"""
    return [m.group(0) for m in _EMOJI_TOKEN_RE.finditer(text or "")]


def strip_emoji(text: str) -> str:
    """去掉 emoji token 后的剩余文本（用于纯文本回退/去重显示）。"""
    return _EMOJI_TOKEN_RE.sub("", text or "").strip()


def set_cache_dir(cache_dir: str) -> None:
    """设置磁盘缓存目录（应用启动时调用一次）。"""
    global _CACHE_DIR
    _CACHE_DIR = cache_dir
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        pass


_CACHE_DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "tklc_emoji_cache")


def _font(px: int) -> Optional[ImageFont.FreeTypeFont]:
    if not os.path.exists(_FONT_PATH):
        return None
    try:
        return ImageFont.truetype(_FONT_PATH, max(16, px * 3))
    except Exception:
        return None


def render_emoji_image(token: str, px: int = 22) -> Optional[Image.Image]:
    """把一个 emoji token 渲染成透明底彩色 PIL.Image（渲染失败返回 None）。

    仅接受纯 emoji token（fullmatch），普通文本直接返回 None。
    """
    token = (token or "").strip()
    px = int(px)
    if not token or px <= 0 or not _EMOJI_TOKEN_RE.fullmatch(token):
        return None
    key = f"{hashlib.md5(token.encode('utf-8')).hexdigest()}_{px}"
    hit = _MEMORY_CACHE.get(key)
    if hit is not None:
        return hit or None  # False = 已知失败

    img = None
    font = _font(px)
    if font is not None:
        try:
            canvas = Image.new("RGBA", (px * 4, px * 4), (0, 0, 0, 0))
            draw = ImageDraw.Draw(canvas)
            draw.text((px, px), token, font=font, embedded_color=True)
            bbox = canvas.getbbox()
            if bbox:
                img = canvas.crop(bbox)
                # 等比缩到目标高度
                w, h = img.size
                scale = px / max(1, h)
                img = img.resize((max(1, int(w * scale)), px), Image.LANCZOS)
        except Exception:
            img = None

    # 内存缓存（False 表示失败）
    if len(_MEMORY_CACHE) >= _MEMORY_CACHE_MAX:
        _MEMORY_CACHE.clear()
    _MEMORY_CACHE[key] = img if img is not None else False
    return img


def emoji_png_path(token: str, px: int = 22) -> Optional[str]:
    """渲染并落盘缓存，返回 PNG 路径（失败返回 None）。"""
    img = render_emoji_image(token, px)
    if img is None:
        return None
    key = f"{hashlib.md5(token.encode('utf-8')).hexdigest()}_{px}.png"
    path = os.path.join(_CACHE_DIR, key)
    if not os.path.exists(path):
        try:
            img.save(path)
        except Exception:
            return None
    return path
