"""导出数据模型与列定义。"""
from __future__ import annotations

from dataclasses import dataclass

# 导出列（与需求 §11/§13 字段一致）
VIDEO_HEADERS = [
    "account",        # 账号 ID
    "username",       # 用户名 @handle
    "video_id",       # 作品 ID
    "publish_time",   # 发布时间
    "publish_date",   # 发布日期
    "video_url",      # 作品 URL
    "collect_time",   # 采集时间
    "task_id",        # 任务 ID
    "status",         # 状态
]

ACCOUNT_HEADERS = ["account", "username", "target_count", "actual_count", "status"]


@dataclass
class ExportRow:
    account: str = ""
    username: str = ""
    video_id: str = ""
    publish_time: str = ""
    publish_date: str = ""
    video_url: str = ""
    collect_time: str = ""
    task_id: str = ""
    status: str = ""


@dataclass
class AccountStat:
    account: str = ""
    username: str = ""
    target_count: int = 0
    actual_count: int = 0
    status: str = ""
