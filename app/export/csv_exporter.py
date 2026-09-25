"""CSV 导出：UTF-8（带 BOM），正确处理中文/逗号/引号/换行。"""
from __future__ import annotations

import csv
from typing import List

from .models import VIDEO_HEADERS, ExportRow


def export_csv(rows: List[ExportRow], path: str) -> None:
    # utf-8-sig 写入 BOM，保证 Excel 打开中文不乱码；csv 模块自动转义逗号/引号/换行
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(VIDEO_HEADERS)
        for r in rows:
            writer.writerow([
                r.account, r.username, r.video_id, r.publish_time, r.publish_date,
                r.video_url, r.collect_time, r.task_id, r.status,
            ])
