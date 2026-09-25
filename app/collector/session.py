"""SessionManager —— 持久化登录态管理（P4）。

- 每个账号独立 user_data_dir（持久化 context 自动保存 cookie）。
- ensure_login：检测登录态 / CAPTCHA / 安全验证，失效抛 LoginRequired，
  由上层 TaskRunner/Engine 标记失败，不阻断整体任务。
- 不绕过任何验证：只检测、不破解。
"""
from __future__ import annotations

import os
import re
from typing import Any

from .exceptions import LoginRequired


class SessionManager:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def user_data_dir_for(self, account) -> str:
        """返回某账号的持久化目录路径。"""
        name = account.account_id or account.username or "account"
        safe = re.sub(r"[^\w\-]", "_", name)
        return os.path.join(self.data_dir, "sessions", safe)

    # URL 层面的登录/验证跳转特征（页面真实跳转才命中，可靠）
    _URL_LOGIN_HINTS = ("/login", "/signup", "/log-in", "/sign-in")
    _URL_CAPTCHA_HINTS = ("/captcha", "/challenge", "/verify")

    # 页面 HTML 层面的风控特征词 —— 只保留探针在真实验证页上实测过的两个精确短语。
    # ⚠️ 不要随意扩充：TikTok 正常主页的 JS/多语言文案里含有 "captcha"、"not a robot"、
    # "security verification"、"log in to continue" 等字符串，粗粒子串匹配必然误判
    # （2026-09-25 曾因词表过宽导致全部账号被误报「触发安全验证」）。
    # 判定原则（见 docs/PROBE_REPORT.md §五）：信 URL 跳转，慎信页面内容。
    _HTML_CHALLENGE_HINTS = (
        "verify to continue",
        "unusual activity",
    )

    def ensure_login(self, page: Any) -> None:
        """检查登录态；失效/CAPTCHA/安全验证抛 LoginRequired。"""
        url = (page.url or "").lower()
        if any(h in url for h in self._URL_LOGIN_HINTS):
            raise LoginRequired(self._login_hint())
        if any(h in url for h in self._URL_CAPTCHA_HINTS):
            raise LoginRequired(
                "触发验证码/安全验证：请在「设置」关闭「后台采集」切到有窗口模式，"
                "重新采集该账号并在弹出的浏览器中手动完成验证。")
        try:
            html = (page.content() or "").lower()
        except Exception:
            return
        if self.detect_challenge(html):
            raise LoginRequired(
                "触发安全验证/限流校验：请人工处理后重试；"
                "若持续出现，可调大「账号间隔」降低采集频率。")

    @staticmethod
    def detect_challenge(html: str) -> bool:
        """判断页面 HTML 是否命中风控/验证特征（供采集过程二次校验）。"""
        h = (html or "").lower()
        return any(k in h for k in SessionManager._HTML_CHALLENGE_HINTS)

    @staticmethod
    def _login_hint() -> str:
        return ("账号未登录或登录已失效：请在「设置」临时关闭「后台采集」，"
                "切回有窗口模式后重新采集，在弹出的浏览器中手动登录一次；"
                "登录成功后即可切回后台采集。")
