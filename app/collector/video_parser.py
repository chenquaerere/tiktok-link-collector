"""VideoParser —— 作品 URL / video_id / 发布时间原始字段解析（P6/P7）。

数据来源（真实探针验证）：
- 一级来源：GET /api/post/item_list/ 响应体 itemList[]，字段：
    id          = video_id（19 位数字，全局唯一）
    createTime  = Unix 秒级时间戳（绝对发布时间）
    desc        = 文案
    author.uniqueId = 用户名
- 作品 URL = https://www.tiktok.com/@{uniqueId}/video/{id}

设计原则：
- 纯函数，输入 item_list 响应 JSON 文本，输出 ParsedVideoItem 列表。
- 用「递归查找含 id + createTime 的对象」通用定位，避免硬编码 itemList 路径，
  页面结构变化时靠重新解析证据即可适配。
- 绝不从页面显示文本猜 URL / 猜日期。
"""
from __future__ import annotations

import json
from typing import Any, List, Optional

from app.core.models import ParsedVideoItem


class VideoParser:
    def __init__(self):
        # 若 TikTok 后续把 itemList 改名，可在这里扩展候选字段名
        self.item_list_keys = ("itemList", "items", "awemeList", "videos")

    # ---- 纯函数：item_list 响应解析 ----
    def parse_item_list(self, body: str) -> List[ParsedVideoItem]:
        """解析 item_list API 响应体，返回作品列表（保持返回顺序=页面时间倒序）。"""
        if not body:
            return []
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return []

        items = self._extract_items(data)
        out: List[ParsedVideoItem] = []
        seen = set()
        for o in items:
            vid = _to_str(o.get("id"))
            if not vid or vid in seen:
                continue
            seen.add(vid)
            parsed = self._to_item(o, vid)
            if parsed is not None:
                out.append(parsed)
        return out

    # ---- 内部 ----
    def _extract_items(self, data: Any) -> List[dict]:
        """优先从已知字段名取列表；否则递归查找含 id+createTime 的对象。"""
        if isinstance(data, dict):
            for key in self.item_list_keys:
                v = data.get(key)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
        # 兜底：递归通用定位
        found = self._find_item_objects(data)
        # 按 createTime 倒序，保证与页面一致（最新在前）
        found.sort(key=lambda o: (o.get("createTime") or 0), reverse=True)
        return found

    @staticmethod
    def _find_item_objects(obj: Any, depth: int = 0, out: Optional[List[dict]] = None) -> List[dict]:
        if out is None:
            out = []
        if depth > 12:
            return out
        if isinstance(obj, dict):
            _id = obj.get("id")
            ct = obj.get("createTime")
            if _is_video_id(_id) and ct is not None:
                out.append(obj)
            for v in obj.values():
                VideoParser._find_item_objects(v, depth + 1, out)
        elif isinstance(obj, list):
            for v in obj:
                VideoParser._find_item_objects(v, depth + 1, out)
        return out

    @staticmethod
    def _to_item(o: dict, vid: str) -> Optional[ParsedVideoItem]:
        author = o.get("author") or {}
        username = author.get("uniqueId") or ""
        # 昵称：item_list 的 author.nickname（TikTok 显示名），实测可直接取到，
        # 用于账号管理页辨识账号，无需额外请求。
        nickname = author.get("nickname") or ""
        create_time = o.get("createTime")
        return ParsedVideoItem(
            video_id=vid,
            username=username,
            nickname=nickname,
            raw_url=f"https://www.tiktok.com/@{username}/video/{vid}" if username else "",
            raw_publish_time=create_time,   # Unix 秒（int/str 均可，DateResolver 会处理）
            time_source="epoch" if create_time is not None else "none",
        )


def _is_video_id(v: Any) -> bool:
    """video_id 是 15 位以上的数字串。"""
    if isinstance(v, bool):
        return False
    s = _to_str(v)
    return s.isdigit() and len(s) >= 15


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)
