"""任务调度测试：单账号失败隔离、重试、停止、恢复（去重不重复）。"""
from __future__ import annotations

import unittest

from app.collector.task_runner import TaskRunner, summarize
from app.core.date_resolver import DateResolver
from app.core.dedup import VideoDedup
from app.core.models import Account
from mocks.mock_provider import MockTikTokProvider

TARGET = "2026-09-24"


def _acc(aid, uname, count=4):
    return Account(account_id=aid, username=uname,
                   profile_url=f"https://www.tiktok.com/@{uname}",
                   collect_count=count)


def _scenario(acc):
    return acc.username.rsplit("_", 1)[1]


def _resolver():
    return DateResolver("Asia/Shanghai")


class TestTaskRunner(unittest.TestCase):
    def _provider(self):
        return MockTikTokProvider(TARGET)

    def test_single_account_failure_isolated(self):
        provider = self._provider()

        def fetcher(acc):
            if acc.account_id == "acc_B":
                raise RuntimeError("登录失效")
            if acc.account_id == "acc_C":
                return provider.fetch("E")  # 独立 4 条（id 5xx）
            return provider.fetch("A")  # 今天 4 条

        accounts = [_acc("acc_A", "user_A"), _acc("acc_B", "user_B"), _acc("acc_C", "user_C")]
        results = TaskRunner(_resolver()).run(accounts, fetcher, TARGET)
        by_id = {r.account_id: r for r in results}
        self.assertEqual(by_id["acc_A"].status, "completed")
        self.assertEqual(by_id["acc_B"].status, "failed")
        self.assertEqual(by_id["acc_C"].status, "completed")
        # 整体汇总：2 成功 1 失败，任务未中断
        s = summarize(results)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["actual_total"], 4 + 0 + 4)  # A=4, B=0, C=4

    def test_retry_then_success(self):
        provider = self._provider()
        calls = {"acc_B": 0}

        def fetcher(acc):
            if acc.account_id == "acc_B":
                calls["acc_B"] += 1
                if calls["acc_B"] == 1:
                    raise RuntimeError("临时失败")
            return provider.fetch("A")  # 4 条

        accounts = [_acc("acc_B", "user_B")]
        runner = TaskRunner(_resolver(), max_retry=3)
        results = runner.run(accounts, fetcher, TARGET)
        self.assertEqual(results[0].status, "completed")
        self.assertEqual(results[0].attempts, 2)

    def test_retry_exhausted_marks_failed(self):
        provider = self._provider()

        def fetcher(acc):
            raise RuntimeError("持续失败")

        accounts = [_acc("acc_A", "user_A")]
        runner = TaskRunner(_resolver(), max_retry=2)
        results = runner.run(accounts, fetcher, TARGET)
        self.assertEqual(results[0].status, "failed")
        self.assertIn("重试 2 次", results[0].error_reason)

    def test_stop_before_run_all_skipped(self):
        provider = self._provider()
        runner = TaskRunner(_resolver())
        runner.request_stop()
        results = runner.run([_acc("acc_A", "user_A")], lambda acc: provider.fetch("A"), TARGET)
        self.assertEqual(results[0].status, "skipped")

    def test_stop_after_first_account(self):
        provider = self._provider()
        runner = TaskRunner(_resolver())

        def fetcher(acc):
            if acc.account_id == "acc_B":
                runner.request_stop()
            return provider.fetch(_scenario(acc))

        accounts = [_acc("acc_A", "user_A"), _acc("acc_B", "user_B"), _acc("acc_C", "user_C")]
        results = runner.run(accounts, fetcher, TARGET)
        # A 完成；B 在 fetch 阶段触发停止后仍完成本次；C 被跳过
        self.assertEqual(results[0].status, "completed")
        self.assertEqual(results[2].status, "skipped")

    def test_resume_skips_duplicates_and_fills(self):
        # 去重器已有 101、102 → 跳过后继续采新的（新语义：不足会用更早作品补足）
        dedup = VideoDedup(initial={"101", "102"})
        runner = TaskRunner(_resolver(), dedup=dedup)
        provider = self._provider()
        results = runner.run([_acc("acc_A", "user_A", count=4)],
                             lambda acc: provider.fetch("A"), TARGET)
        self.assertEqual(results[0].actual_count, 4)
        self.assertEqual({v.video_id for v in results[0].videos},
                         {"103", "104", "105", "106"})

    def test_summarize(self):
        # 用真实 runner 产出结果再汇总
        provider = self._provider()
        accounts = [_acc("acc_A", "user_A", 4), _acc("acc_B", "user_B", 4), _acc("acc_C", "user_C", 4)]
        results = TaskRunner(_resolver()).run(
            accounts, lambda acc: provider.fetch(_scenario(acc)), TARGET)
        s = summarize(results)
        self.assertEqual(s["account_count"], 3)
        self.assertEqual(s["completed"], 2)   # A(4) + C(昨日4条照采)
        self.assertEqual(s["partial"], 1)     # B 只有 2 条
        self.assertEqual(s["empty"], 0)
        self.assertEqual(s["actual_total"], 10)

    def test_per_account_collect_count(self):
        # 每账号独立采集数量：A=2，B=4
        provider = self._provider()

        def fetcher(acc):
            if acc.account_id == "acc_A":
                return provider.fetch("A")
            return provider.fetch("E")

        accounts = [_acc("acc_A", "user_A", count=2), _acc("acc_B", "user_B", count=4)]
        results = TaskRunner(_resolver()).run(accounts, fetcher, TARGET)
        by = {r.account_id: r for r in results}
        self.assertEqual(by["acc_A"].target_count, 2)
        self.assertEqual(by["acc_A"].actual_count, 2)
        self.assertEqual(by["acc_B"].target_count, 4)
        self.assertEqual(by["acc_B"].actual_count, 4)


if __name__ == "__main__":
    unittest.main()
