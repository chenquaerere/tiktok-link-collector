"""采集引擎异常类型。"""


class CollectorError(Exception):
    """采集引擎基础异常。"""


class LoginRequired(CollectorError):
    """需要人工登录/验证（CAPTCHA / 重新登录 / 访问限制）。"""


class RateLimited(CollectorError):
    """触发 TikTok 限流（HTTP 429 / 请求过于频繁），应退避等待后重试。"""


class PageLoadFailed(CollectorError):
    """页面加载失败。"""


class ParseFailed(CollectorError):
    """页面解析失败（结构变化或数据缺失）。"""
