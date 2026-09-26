"""结果 / 复制 / 历史服务层（P17/P18/P20）。

- ResultService：按账号/日期/任务查询作品、生成纯 URL 复制文本、账号统计、
  历史任务列表与详情。
- 复制文本只输出纯 URL（每行一个），方便粘贴到后续作品回填工具。
"""
from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional

from app.core.models import status_message
from app.db.database import Database


class ResultService:
    def __init__(self, db: Database):
        self.db = db

    # ---- 查询 ----
    def query_videos(self, *, account_id: Optional[str] = None,
                     publish_date: Optional[str] = None,
                     task_id: Optional[str] = None):
        return self.db.query_videos(account_id=account_id,
                                    publish_date=publish_date, task_id=task_id)

    # ---- 复制 ----
    def clear_videos(self, *, account_id: Optional[str] = None,
                     publish_date: Optional[str] = None) -> int:
        """清空作品链接（与查询同套过滤条件；全空 = 清空全部），返回删除条数。"""
        return self.db.delete_videos(account_id=account_id, publish_date=publish_date)

    def to_url_text(self, rows) -> str:
        """纯 URL 文本：每条链接后跟一个空行（按视频去重，保持顺序）。

        空行分隔便于逐条框选/复制，也方便肉眼核对。
        """
        seen = set()
        urls = []
        for r in rows:
            vid = r["video_id"]
            if vid in seen:
                continue
            seen.add(vid)
            urls.append(r["video_url"])
        return "\n\n".join(urls)

    def to_grouped_text(self, rows) -> str:
        """账号分组文本：@username 下跟随其 URL，每条链接后空一行。"""
        groups: "OrderedDict[str, List[str]]" = OrderedDict()
        seen = set()
        for r in rows:
            vid = r["video_id"]
            if vid in seen:
                continue
            seen.add(vid)
            groups.setdefault(r["username"], []).append(r["video_url"])
        lines = []
        for uname, urls in groups.items():
            lines.append(f"@{uname}")
            for u in urls:
                lines.append(u)
                lines.append("")
        return "\n".join(lines).rstrip("\n")

    # ---- 账号统计 ----
    def account_stats(self, rows) -> List[dict]:
        """把作品行聚合为每账号统计（账号/目标/实际/状态）。"""
        stats: "OrderedDict[str, dict]" = OrderedDict()
        for r in rows:
            key = r["account_id"]
            if key not in stats:
                stats[key] = {"account": r["account_id"], "username": r["username"],
                              "actual_count": 0}
            stats[key]["actual_count"] += 1
        return list(stats.values())

    # ---- 历史 ----
    def list_tasks(self, limit: int = 50):
        return self.db.list_tasks(limit=limit)

    def task_detail(self, task_id: str) -> dict:
        task = self.db.get_task(task_id)
        accounts = self.db.list_task_accounts(task_id)
        videos = self.db.query_videos(task_id=task_id)
        return {"task": task, "accounts": accounts, "videos": videos}

    def task_video_urls(self, task_id: str) -> str:
        """按任务导出纯 URL 文本。"""
        return self.to_url_text(self.db.query_videos(task_id=task_id))

    def date_video_urls(self, publish_date: str) -> str:
        """按发布日期导出纯 URL 文本。"""
        return self.to_url_text(self.db.query_videos(publish_date=publish_date))
