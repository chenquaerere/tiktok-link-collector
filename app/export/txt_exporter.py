"""TXT 导出：纯 URL 模式 + 账号分组模式。"""
from __future__ import annotations

from collections import OrderedDict
from typing import List

from .models import ExportRow


def export_urls(rows: List[ExportRow], path: str) -> None:
    """纯 URL 模式：每条链接后跟一个空行。"""
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r.video_url + "\n\n")


def export_grouped(rows: List[ExportRow], path: str) -> None:
    """账号分组模式：@username 下跟随其 URL，每条链接后空一行。"""
    groups: "OrderedDict[str, List[str]]" = OrderedDict()
    for r in rows:
        groups.setdefault(r.username, []).append(r.video_url)

    with open(path, "w", encoding="utf-8") as f:
        for uname, urls in groups.items():
            f.write(f"@{uname}\n")
            for u in urls:
                f.write(u + "\n\n")
