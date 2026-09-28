"""核心采集逻辑（纯函数，不依赖浏览器/UI）。

规则（2026-09-25 起，用户规定）：
- 不过滤日期：按主页时间倒序直接取账号最新 target_count 条作品。
- 发布时间尽力解析并记录；无法确认的照常采集（publish_date 记空）。
- 置顶作品（2026-09-28）：
  · 置顶不占「最新 N 条」名额（置顶被排在列表最前、时间却是旧的，会挤掉新作品）；
  · 但若置顶发布于**今天或昨天**，它本身就是新作品 → **额外采集**（结果会多于 N 条）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List, Set

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


def recent_dates(resolver: DateResolver, days: int = 2) -> Set[str]:
    """最近 N 天（含今天）的日期集合，按 resolver 的时区。

    用于判断置顶作品是否属于「今天或昨天发布」—— 这类置顶本身是新作品，
    应当额外采集（不占「最新 N 条」名额）。
    """
    now = datetime.now(resolver.tz)
    return {(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(max(1, days))}


def build_video(item: ParsedVideoItem, resolver: DateResolver, *,
                account_id: str, username: str, diag: dict) -> Video:
    """解析发布时间并构造入库用 Video（置顶与非置顶共用）。"""
    resolve_item(item, resolver)
    publish_time = ""
    publish_date = ""
    if item.confidence == DateConfidence.CONFIRMED.value and item.publish_datetime:
        diag["date_resolved"] += 1
        publish_time = item.publish_datetime.strftime("%Y-%m-%d %H:%M:%S")
        publish_date = item.publish_date or ""
    else:
        diag["date_unconfirmed"] += 1
    normalized, vid, _ = normalize_url(item.raw_url, username_hint=username)
    return Video(
        video_id=vid or item.video_id,
        account_id=account_id,
        username=username,
        video_url=normalized or item.raw_url,
        publish_time=publish_time,
        publish_date=publish_date,
    )


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
    「今天/昨天发布的置顶作品」会被额外采集，因此最终条数可能多于 target_count。
    """
    diag = {
        "found": 0,
        "date_resolved": 0,
        "date_unconfirmed": 0,
        "duplicates": 0,
        "pinned_skipped": 0,
        "pinned_collected": 0,
        "collected": 0,
    }
    selected: List[Video] = []
    counted = 0                      # 计入「最新 N 条」的数量（额外采集的置顶不计）
    recent = recent_dates(resolver, 2)

    for item in items:
        diag["found"] += 1

        # 1) 置顶作品：今天/昨天的额外采集；较旧的跳过（都不占名额）
        if getattr(item, "is_pinned", False):
            resolve_item(item, resolver)
            if (item.publish_date or "") not in recent:
                diag["pinned_skipped"] += 1
                continue
            video = build_video(item, resolver, account_id=account_id,
                                username=username, diag=diag)
            if dedup.is_duplicate(video.video_id):
                diag["duplicates"] += 1
                continue
            dedup.mark(video.video_id)
            selected.append(video)
            diag["pinned_collected"] += 1
            diag["collected"] += 1
            continue

        # 2) 同一作品在列表里重复出现 → 跳过且不计数。
        #    放在数量检查之前，保证 duplicates 统计准确（与 engine._collect_once 保持一致）。
        if dedup.is_duplicate(item.video_id):
            diag["duplicates"] += 1
            continue

        # 3) 非置顶作品已取满 → 停止
        if counted >= target_count:
            break

        # 4) 解析发布时间并纳入结果
        video = build_video(item, resolver, account_id=account_id,
                            username=username, diag=diag)
        dedup.mark(item.video_id)
        selected.append(video)
        counted += 1
        diag["collected"] += 1

    return AccountCollectResult(
        account_id=account_id,
        username=username,
        target_date=target_date,
        target_count=target_count,
        actual_count=len(selected),
        status=_status_for(target_count, counted),
        videos=selected,
        diagnostics=diag,
    )


def _status_for(target_count: int, actual: int) -> str:
    if actual >= target_count:
        return "completed"
    if actual > 0:
        return "partial"   # 当日作品不足
    return "empty"         # 当日无作品

