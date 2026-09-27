"""任务调度测试：单账号失败隔离、重试、停止、每次抓取均取最新 N 条（无跨运行去重）。"""
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

    def test_no_cross_run_dedup_returns_newest(self):
        """★ 回归：不得再有「跨运行去重」。

        旧行为（已废弃）：去重器预载**库中已有 ID**，采集时把「已采过的作品」当重复跳过，
        于是最新的 101/102 被跳过、只拿到 103~106 —— 既不是最新，也可能凑不够数量。
        用户要求（2026-09-27）：不管之前采过没有，每次抓取都从最新一条开始取满数量。
        """
        dedup = VideoDedup(initial={"101", "102"})   # 模拟「库里已经有这两条」
        self.assertEqual(len(dedup), 2)
        runner = TaskRunner(_resolver())
        provider = self._provider()
        results = runner.run([_acc("acc_A", "user_A", count=4)],
                             lambda acc: provider.fetch("A"), TARGET)
        self.assertEqual(results[0].actual_count, 4)
        self.assertEqual({v.video_id for v in results[0].videos},
                         {"101", "102", "103", "104"},
                         "必须包含最新的 101/102，不能被历史采集记录挤掉")

    def test_rerun_returns_identical_newest_set(self):
        """★ 回归：同一账号连跑两次，结果必须完全一致（重新抓取 = 重新拿最新 N 条）。"""
        provider = self._provider()

        def fetcher(_acc_):
            return provider.fetch("A")

        first = TaskRunner(_resolver()).run([_acc("acc_A", "user_A", 4)], fetcher, TARGET)[0]
        second = TaskRunner(_resolver()).run([_acc("acc_A", "user_A", 4)], fetcher, TARGET)[0]
        ids1 = [v.video_id for v in first.videos]
        ids2 = [v.video_id for v in second.videos]
        self.assertEqual(ids1, ids2, "两次抓取结果必须一致")
        self.assertEqual(ids1, ["101", "102", "103", "104"])

    def test_duplicate_within_same_run_only_once(self):
        """同一账号同一次采集内，同一作品重复出现（置顶等）只算一次，不占两个名额。"""
        provider = self._provider()

        def fetcher(_acc_):
            items = provider.fetch("A")[:4]
            return items + items[:1]          # 第一条在列表里重复渲染一次

        r = TaskRunner(_resolver()).run([_acc("acc_A", "user_A", 4)], fetcher, TARGET)[0]
        ids = [v.video_id for v in r.videos]
        self.assertEqual(len(ids), len(set(ids)), "结果里不得有重复视频")
        self.assertEqual(ids, ["101", "102", "103", "104"])
        self.assertEqual(r.diagnostics["duplicates"], 1)

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
