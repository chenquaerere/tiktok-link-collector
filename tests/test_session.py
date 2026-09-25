"""SessionManager 回归测试 —— 重点防「风控误判」（2026-09-25 事故回归）。

背景：P0 曾把 HTML 特征词扩到 10+ 个（captcha / not a robot / security
verification 等），这些词在 TikTok 正常主页的 JS/多语言文案里必然存在，
导致全部账号被误报「触发安全验证」。本测试固化探针实测结论：
正常页面（即使含风控相关字符串资源）绝不能被判为验证页。
"""
import unittest

from app.collector.exceptions import LoginRequired
from app.collector.session import SessionManager


class _FakePage:
    """最小 page 桩：只提供 url 与 content()。"""

    def __init__(self, url="https://www.tiktok.com/@demo_alpha", html=""):
        self.url = url
        self._html = html

    def content(self):
        return self._html


# 模拟真实 TikTok 主页 HTML：含验证码组件配置、多语言文案、登录弹窗模板等
# 干扰字符串（真实页面一定会有），外加 SSR 数据与 item_list 请求残留。
NORMAL_TIKTOK_HTML = """
<!DOCTYPE html><html><head>
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
{"__DEFAULT_SCOPE__":{"webapp.user-detail":{"userInfo":{"user":{
"uniqueId":"demo_alpha","createTime":"1500000000"},"itemList":[]}}}}
</script>
</head><body>
<script>window.CAPTCHA_DOMAIN="https://captcha.tiktok.com";</script>
<i18n>{"captcha.verify.title":"Confirm you're not a robot",
"captcha.slide":"Slide to verify","login.modal.title":"Log in to continue",
"login.modal.subtitle":"Please log in to continue",
"securityVerification.upgrade":"Security verification required for some actions",
"rateLimit.retry":"Too many requests. Please try again later."}</i18n>
<div class="tiktok-video-feed">videos here</div>
<a href="/@demo_alpha/video/7689051423832575001">video</a>
</body></html>
"""


class TestEnsureLoginNoFalsePositive(unittest.TestCase):
    """核心诉求：正常页面绝不能抛 LoginRequired。"""

    def test_normal_page_with_captcha_strings_passes(self):
        """含 captcha/robot/登录文案等资源字符串的正常主页 → 不误判。"""
        page = _FakePage(html=NORMAL_TIKTOK_HTML)
        SessionManager("test_data_dir").ensure_login(page)  # 不应抛异常

    def test_normal_page_empty_html_passes(self):
        page = _FakePage(html="<html><body>ok</body></html>")
        SessionManager("test_data_dir").ensure_login(page)

    def test_normal_page_content_error_passes(self):
        """content() 抛异常（页面跳转中）→ 静默放行，由后续流程兜底。"""

        class _Boom(_FakePage):
            def content(self):
                raise RuntimeError("page navigating")

        SessionManager("test_data_dir").ensure_login(_Boom(html=""))


class TestEnsureLoginRealDetection(unittest.TestCase):
    """真实异常场景必须仍能检出。"""

    def test_login_url_redirect(self):
        page = _FakePage(url="https://www.tiktok.com/login?redirect=...")
        with self.assertRaises(LoginRequired):
            SessionManager("test_data_dir").ensure_login(page)

    def test_captcha_url_redirect(self):
        page = _FakePage(url="https://www.tiktok.com/captcha")
        with self.assertRaises(LoginRequired):
            SessionManager("test_data_dir").ensure_login(page)

    def test_verify_to_continue_html(self):
        """探针实测过的真实验证页文案。"""
        page = _FakePage(html="<div>Verify to continue to TikTok</div>")
        with self.assertRaises(LoginRequired):
            SessionManager("test_data_dir").ensure_login(page)

    def test_unusual_activity_html(self):
        page = _FakePage(html="<p>Unusual activity detected</p>")
        with self.assertRaises(LoginRequired):
            SessionManager("test_data_dir").ensure_login(page)


class TestDetectChallenge(unittest.TestCase):
    def test_challenge_words_hit(self):
        self.assertTrue(SessionManager.detect_challenge("Verify to continue"))
        self.assertTrue(SessionManager.detect_challenge("UNUSUAL ACTIVITY"))

    def test_resource_strings_not_hit(self):
        """JS 资源里的风控字符串不能命中（事故回归）。"""
        self.assertFalse(SessionManager.detect_challenge(NORMAL_TIKTOK_HTML))
        self.assertFalse(SessionManager.detect_challenge("captchaDomain=..."))
        self.assertFalse(SessionManager.detect_challenge("not a robot"))
        self.assertFalse(SessionManager.detect_challenge("security verification"))
        self.assertFalse(SessionManager.detect_challenge("too many requests"))

    def test_empty_none_safe(self):
        self.assertFalse(SessionManager.detect_challenge(""))
        self.assertFalse(SessionManager.detect_challenge(None))


if __name__ == "__main__":
    unittest.main()
