"""采集结果页回归：启动必须清空 + 采集时间列。

对应两个用户反馈的细节：
1. 打开程序时结果区必须为空 —— 不能残留上次采集的链接
   （只有「本次采集完成」或「主动点查询」才显示）
2. 结果表格需要显示采集时间
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestResultsIdleAndCollectTime(unittest.TestCase):
    def _results_src(self) -> str:
        return (ROOT / "app/ui/pages/results_page.py").read_text(encoding="utf-8")

    def test_has_collect_time_column(self):
        """表格必须含「采集时间」列，数据来自 first_collect_time。"""
        s = self._results_src()
        self.assertIn('"collect_time"', s)
        self.assertIn("first_collect_time", s)
        self.assertIn("采集时间", s)

    def test_refresh_respects_session_flag(self):
        """refresh() 必须先判断本次会话是否采集过，否则走清空态。"""
        s = self._results_src()
        body = s.split("def refresh(")[1].split("def _on_query_clicked")[0]
        self.assertIn("collected_this_session", body)
        self.assertIn("_show_idle()", body)

    def test_idle_state_clears_panel(self):
        """清空态必须同步清掉链接面板与表格，不能只隐藏表格。"""
        s = self._results_src()
        body = s.split("def _show_idle(")[1].split("def _query(")[0]
        self.assertIn("_link_panel.set_data([", body)
        self.assertIn("_table.clear()", body)
        self.assertIn("本次尚未采集", body)

    def test_scope_defaults_to_session(self):
        """数据范围默认「本次采集」——默认只显示本次任务的结果。"""
        s = self._results_src()
        self.assertIn('SCOPE_SESSION = "本次采集"', s)
        self.assertIn("_scope_menu.set(SCOPE_SESSION)", s)

    def test_query_filters_by_last_task_id(self):
        """「本次采集」必须按 last_task_id 过滤，否则会列出全库历史。

        这是用户实测问题：只选 1 个账号采 3 条，结果页却出现一堆旧链接。
        """
        s = self._results_src()
        body = s.split("def _query(")[1].split("def _rebuild_status_options")[0]
        self.assertIn("last_task_id", body)
        self.assertIn("task_id=task_id", body)

    def test_sorted_by_collect_time_desc(self):
        """结果按「采集时间」倒序 —— 刚采的排最前。"""
        s = self._results_src()
        body = s.split("def _query(")[1].split("def _rebuild_status_options")[0]
        self.assertIn("first_collect_time", body)
        self.assertIn("reverse=True", body)

    def test_latest_collect_time_label(self):
        """底部显示「最近采集 <时间>」，且用绿色（success）。"""
        s = self._results_src()
        self.assertIn("_latest_lbl", s)
        self.assertIn("最近采集", s)
        self.assertIn('text_color=COLORS["success"]', s)

    def test_scope_all_available(self):
        """提供「全部历史」出口，方便回看以前采集过的链接。"""
        s = self._results_src()
        self.assertIn('SCOPE_ALL = "全部历史"', s)

    def test_hover_column_index_dynamic(self):
        """悬停提示的列索引必须按列名取，插入新列后不能错位。"""
        s = self._results_src()
        self.assertIn("columns.index", s)
        self.assertNotIn('col != "#5"', s)

    def test_session_flag_not_persisted(self):
        """会话标记只存在于内存，不写库、不读配置。"""
        s = (ROOT / "app/app.py").read_text(encoding="utf-8")
        self.assertIn("collected_this_session = False", s)
        self.assertNotIn('set("collected_this_session"', s)

    def test_collect_marks_session_after_run(self):
        """采集结束必须打标记，结果页据此显示链接。"""
        s = (ROOT / "app/ui/pages/collect_page.py").read_text(encoding="utf-8")
        body = s.split("def _on_done(")[1].split("def _on_error(")[0]
        self.assertIn("collected_this_session = True", body)

    def test_window_shutdown_cancels_timers(self):
        """退出前必须取消除定时器，避免窗口销毁后触发无效回调。"""
        s = (ROOT / "app/ui/app_window.py").read_text(encoding="utf-8")
        self.assertIn("def shutdown(", s)
        self.assertIn("after_cancel", s)
        self.assertIn("def destroy(", s)


if __name__ == "__main__":
    unittest.main()
