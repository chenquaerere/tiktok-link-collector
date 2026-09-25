"""任务调度器：多账号串行采集、单账号失败隔离、自动重试、停止控制。

采集源通过 fetcher 注入（真实环境为 Playwright，测试为 Mock），实现逻辑与网络解耦。
"""
from __future__ import annotations

import threading
import time
from typing import Callable, List

from app.core.collect_logic import collect_for_account
from app.core.date_resolver import DateResolver
from app.core.dedup import VideoDedup
from app.core.models import Account, AccountCollectResult, ParsedVideoItem

Fetcher = Callable[[Account], List[ParsedVideoItem]]


class TaskRunner:
    def __init__(
        self,
        resolver: DateResolver,
        max_retry: int = 3,
        retry_wait: float = 0.0,
        dedup: VideoDedup | None = None,
    ):
        self.resolver = resolver
        self.dedup = dedup or VideoDedup()
        self.max_retry = max(0, max_retry)
        self.retry_wait = max(0.0, retry_wait)
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        self._stop.clear()

    def _stopped(self) -> bool:
        return self._stop.is_set()

    def run(self, accounts: List[Account], fetcher: Fetcher, target_date: str) -> List[AccountCollectResult]:
        results: List[AccountCollectResult] = []
        for acc in accounts:
            if self._stopped():
                results.append(self._skipped(acc, target_date, "任务已停止"))
                continue
            results.append(self._run_with_retry(acc, fetcher, target_date))
        return results

    def _run_with_retry(self, acc: Account, fetcher: Fetcher, target_date: str) -> AccountCollectResult:
        last_error = ""
        for attempt in range(1, self.max_retry + 1):
            if self._stopped():
                return self._failed(acc, target_date, "任务已停止")
            try:
                items = fetcher(acc)
                result = collect_for_account(
                    items,
                    target_date=target_date,
                    target_count=acc.collect_count,
                    account_id=acc.account_id,
                    username=acc.username,
                    resolver=self.resolver,
                    dedup=self.dedup,
                )
                result.attempts = attempt
                return result
            except Exception as exc:  # noqa: BLE001 —— 单个账号失败不得阻断整体任务
                last_error = str(exc) or type(exc).__name__
                if attempt < self.max_retry and self.retry_wait > 0:
                    time.sleep(self.retry_wait)
        return self._failed(acc, target_date, f"重试 {self.max_retry} 次后仍失败: {last_error}")

    def _failed(self, acc: Account, target_date: str, reason: str) -> AccountCollectResult:
        return AccountCollectResult(
            account_id=acc.account_id,
            username=acc.username,
            target_date=target_date,
            target_count=acc.collect_count,
            actual_count=0,
            status="failed",
            error_reason=reason,
            diagnostics={"attempts": 0},
        )

    def _skipped(self, acc: Account, target_date: str, reason: str) -> AccountCollectResult:
        return AccountCollectResult(
            account_id=acc.account_id,
            username=acc.username,
            target_date=target_date,
            target_count=acc.collect_count,
            actual_count=0,
            status="skipped",
            error_reason=reason,
            diagnostics={},
        )


def summarize(results: List[AccountCollectResult]) -> dict:
    """汇总多账号结果，供任务/仪表盘统计。"""
    completed = sum(1 for r in results if r.status == "completed")
    partial = sum(1 for r in results if r.status == "partial")
    empty = sum(1 for r in results if r.status == "empty")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    target_total = sum(r.target_count for r in results)
    actual_total = sum(r.actual_count for r in results)
    return {
        "account_count": len(results),
        "completed": completed,
        "partial": partial,
        "empty": empty,
        "failed": failed,
        "skipped": skipped,
        "target_total": target_total,
        "actual_total": actual_total,
        "success_count": completed + partial,  # 有产出的账号数
    }
