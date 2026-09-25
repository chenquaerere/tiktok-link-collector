"""核心采集逻辑（纯函数，不依赖浏览器/UI）。

规则（2026-09-25 起，用户规定）：
- 不过滤日期：按主页时间倒序直接取账号最新 target_count 条作品。
- 发布时间尽力解析并记录；无法确认的照常采集（publish_date 记空）。
"""
from __future__ import annotations

from typing import Iterable, List

from .date_resolver import DateResolver
from .dedup import VideoDedup
from .models import (
    AccountCollectResult,
    DateConfidence,
    ParsedVideoItem,
    Video,
)
from .url_normalizer import normalize_url


def resolve_item(item: ParsedVideoItem, resolver: DateResolver) -> ParsedVideoItem:
    """解析单条作品发布时间，填充 publish_datetime / publish_date / confidence。"""
    if item.confidence == DateConfidence.UNCONFIRMED.value and item.publish_datetime is None:
        res = resolver.resolve(item.raw_publish_time)
        item.publish_datetime = res.dt
        item.publish_date = res.date_str
        item.confidence = res.confidence
        item.time_source = res.source
    return item


def collect_for_account(
    items: Iterable[ParsedVideoItem],
    *,
    target_date: str,
    target_count: int,
    account_id: str,
    username: str,
    resolver: DateResolver,
    dedup: VideoDedup,
) -> AccountCollectResult:
    """对单个账号执行采集：取最新 target_count 条（不过滤日期）。

    items 假定按页面顺序（通常时间倒序）。target_date 仅作记录标签。
    """
    diag = {
        "found": 0,
        "date_resolved": 0,
        "date_unconfirmed": 0,
        "duplicates": 0,
        "collected": 0,
    }
    selected: List[Video] = []

    for item in items:
        diag["found"] += 1

        # 1) 已达目标数量 → 停止
        if len(selected) >= target_count:
            break

        # 2) 去重
        if dedup.is_duplicate(item.video_id):
            diag["duplicates"] += 1
            continue

        # 3) 解析发布时间（尽力记录；无法确认照常采集）
        resolve_item(item, resolver)
        publish_time = ""
        publish_date = ""
        if item.confidence == DateConfidence.CONFIRMED.value and item.publish_datetime:
            diag["date_resolved"] += 1
            publish_time = item.publish_datetime.strftime("%Y-%m-%d %H:%M:%S")
            publish_date = item.publish_date or ""
        else:
            diag["date_unconfirmed"] += 1

        # 4) 标准化 URL 并纳入结果
        normalized, vid, _ = normalize_url(item.raw_url, username_hint=username)
        video_id = vid or item.video_id
        dedup.mark(video_id)
        selected.append(Video(
            video_id=video_id,
            account_id=account_id,
            username=username,
            video_url=normalized or item.raw_url,
            publish_time=publish_time,
            publish_date=publish_date,
        ))
        diag["collected"] += 1

    return AccountCollectResult(
        account_id=account_id,
        username=username,
        target_date=target_date,
        target_count=target_count,
        actual_count=len(selected),
        status=_status_for(target_count, len(selected)),
        videos=selected,
        diagnostics=diag,
    )


def _status_for(target_count: int, actual: int) -> str:
    if actual >= target_count:
        return "completed"
    if actual > 0:
        return "partial"   # 当日作品不足
    return "empty"         # 当日无作品
