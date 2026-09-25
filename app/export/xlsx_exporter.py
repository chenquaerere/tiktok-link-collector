"""XLSX 导出（openpyxl）：两个 Sheet —— 作品链接 + 账号统计。"""
from __future__ import annotations

from typing import List

from .models import ACCOUNT_HEADERS, VIDEO_HEADERS, AccountStat, ExportRow


def export_xlsx(rows: List[ExportRow], account_stats: List[AccountStat], path: str) -> None:
    from openpyxl import Workbook  # 延迟导入：仅导出 XLSX 时才需要 openpyxl

    wb = Workbook()

    ws1 = wb.active
    ws1.title = "作品链接"
    ws1.append(VIDEO_HEADERS)
    for r in rows:
        ws1.append([
            r.account, r.username, r.video_id, r.publish_time, r.publish_date,
            r.video_url, r.collect_time, r.task_id, r.status,
        ])

    ws2 = wb.create_sheet("账号统计")
    ws2.append(ACCOUNT_HEADERS)
    for s in account_stats:
        ws2.append([s.account, s.username, s.target_count, s.actual_count, s.status])

    wb.save(path)
