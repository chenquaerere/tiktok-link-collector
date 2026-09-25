"""ExportService —— 导出统一入口，聚合 TXT/CSV/XLSX，提供过滤与去重。"""
from __future__ import annotations

from typing import List, Optional

from .csv_exporter import export_csv
from .models import AccountStat, ExportRow
from .txt_exporter import export_grouped, export_urls
from .xlsx_exporter import export_xlsx


class ExportService:
    @staticmethod
    def dedupe_rows(rows: List[ExportRow]) -> List[ExportRow]:
        """按 video_id 去重，保持首次出现顺序。"""
        seen = set()
        out: List[ExportRow] = []
        for r in rows:
            if r.video_id in seen:
                continue
            seen.add(r.video_id)
            out.append(r)
        return out

    @staticmethod
    def filter_rows(rows: List[ExportRow], *, task_id: Optional[str] = None,
                    date: Optional[str] = None) -> List[ExportRow]:
        """按任务 ID / 发布日期过滤。"""
        if task_id is not None:
            rows = [r for r in rows if r.task_id == task_id]
        if date is not None:
            rows = [r for r in rows if r.publish_date == date]
        return rows

    @staticmethod
    def export_txt(rows: List[ExportRow], path: str, mode: str = "urls") -> None:
        if mode == "grouped":
            export_grouped(rows, path)
        else:
            export_urls(rows, path)

    @staticmethod
    def export_csv(rows: List[ExportRow], path: str) -> None:
        export_csv(rows, path)

    @staticmethod
    def export_xlsx(rows: List[ExportRow], account_stats: List[AccountStat], path: str) -> None:
        export_xlsx(rows, account_stats, path)
