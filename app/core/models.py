"""核心数据模型（dataclass），贯穿 UI / 采集 / 持久化各层。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional


class DateConfidence(str, Enum):
    """作品发布时间可信度。"""
    CONFIRMED = "confirmed"            # 绝对时间，可靠，可参与日期匹配
    RELATIVE_ONLY = "relative_only"    # 仅相对时间（"2h ago"），不可靠
    UNCONFIRMED = "unconfirmed"        # 无法确认


class AccountTaskStatus(str, Enum):
    """单个账号在任务中的结果状态。"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"    # 达到目标数量
    PARTIAL = "partial"        # 当日作品不足
    EMPTY = "empty"            # 当日无作品
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class Account:
    account_id: str
    username: str
    profile_url: str
    display_name: str = ""
    remark: str = ""
    region: str = ""                     # 地区分类（越南/缅甸/…，空 = 未分类）
    enabled: bool = True
    login_status: str = "unknown"
    collect_count: int = 4
    created_at: str = ""
    updated_at: str = ""
    last_collect_time: Optional[str] = None
    last_collect_result: str = ""


@dataclass
class ParsedVideoItem:
    """从页面解析出的单条作品原始数据。"""
    video_id: str
    username: str
    nickname: str = ""               # 作者昵称（TikTok 显示名，来自 item_list 的 author.nickname）
    raw_url: str = ""
    raw_publish_time: Any = None  # ISO str / epoch / 相对文本 / None
    time_source: str = "unknown"  # iso / epoch / relative / dom / none
    # 以下由 DateResolver 填充
    publish_datetime: Optional[datetime] = None
    publish_date: Optional[str] = None
    confidence: str = DateConfidence.UNCONFIRMED.value


@dataclass
class Video:
    """入库/输出的规范化作品记录。"""
    video_id: str
    account_id: str
    username: str
    video_url: str
    publish_time: Optional[str] = None   # YYYY-MM-DD HH:mm:ss
    publish_date: Optional[str] = None   # YYYY-MM-DD
    first_collect_time: str = ""         # 首次采集入库时间
    first_task_id: str = ""              # 首次采集所属任务
    status: str = "ok"


@dataclass
class AccountCollectResult:
    """单账号采集结果（含诊断）。"""
    account_id: str
    username: str
    target_date: str
    target_count: int
    actual_count: int
    status: str  # AccountTaskStatus
    videos: List[Video] = field(default_factory=list)
    error_reason: str = ""
    attempts: int = 0
    diagnostics: dict = field(default_factory=dict)


@dataclass
class CollectTask:
    task_id: str
    target_date: str
    created_at: str
    status: str = TaskStatus.PENDING.value
    account_count: int = 0
    target_total: int = 0
    actual_total: int = 0
    success_count: int = 0
    fail_count: int = 0
    completed_at: Optional[str] = None


# 状态 -> 中文文案
STATUS_MESSAGES = {
    AccountTaskStatus.COMPLETED.value: "完成",
    AccountTaskStatus.PARTIAL.value: "当日作品不足",
    AccountTaskStatus.EMPTY.value: "今日没有发现作品",
    AccountTaskStatus.FAILED.value: "失败",
    AccountTaskStatus.SKIPPED.value: "已跳过",
    AccountTaskStatus.PENDING.value: "等待中",
    AccountTaskStatus.RUNNING.value: "采集中",
}


def status_message(status: str, actual: int = 0, target: int = 0) -> str:
    """返回状态的中文文案（不足时补充数量）。"""
    if status == AccountTaskStatus.PARTIAL.value:
        return f"当日仅发现 {actual} 条"
    return STATUS_MESSAGES.get(status, status)
