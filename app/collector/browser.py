"""BrowserManager —— Playwright 浏览器生命周期管理（P4）。

- 惰性导入 playwright（降低启动/打包开销）。
- 持久化 context（launch_persistent_context）：cookie/登录态落盘。
- headless 由调用方传入。headless=True 时使用完整 Chromium 的 new headless
  模式（headless="new"），而非 headless shell —— new 模式渲染引擎与有头一致，
  反自动化检测更弱，且不弹窗、不抢焦点，不影响用户操作电脑。
- 代理由调用方注入（来自 config / 环境变量），本模块不硬编码任何代理地址。
"""
from __future__ import annotations

import threading
from typing import Any, Optional, Tuple

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class BrowserManager:
    def __init__(
        self,
        headless: bool = True,
        proxy: Optional[dict] = None,
        user_agent: str = UA,
        viewport: Tuple[int, int] = (1366, 900),
        extra_args: Optional[list] = None,
    ):
        self.headless = headless
        self.proxy = proxy
        self.user_agent = user_agent
        self.viewport = viewport
        self.extra_args = extra_args or []
        self._playwright: Any = None
        self._owner_thread: Optional[int] = None  # Playwright 绑定的线程

    def start(self) -> None:
        """启动 Playwright（惰性导入 + 线程守卫）。

        Playwright 同步 API 绑定启动它的线程：若在别的线程调用会抛
        greenlet.error: cannot switch to a different thread。
        UI 每次采集都开新线程，因此检测到线程变化时自动重启实例。
        """
        tid = threading.get_ident()
        if self._playwright is not None and self._owner_thread != tid:
            self.stop()  # 旧实例属于已结束/其他线程，安全关闭后重建
        if self._playwright is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._owner_thread = tid

    def new_context(self, user_data_dir: str):
        """为指定账号创建/复用持久化 context。返回 Playwright BrowserContext。

        后台（无头）实现要点：Playwright 的 launch_persistent_context 的 headless
        参数只接受 bool，不接受 "new"；而 headless=True 默认走 chromium-headless-shell
        （指纹明显，易触发 TikTok 风控）。因此这里固定 headless=False 让 playwright
        加载完整 Chromium，再通过 args 注入 `--headless=new` 实现「新无头引擎」——
        渲染引擎与有头一致、反检测更弱，且不弹窗、不抢焦点、不影响用户操作。
        """
        self.start()
        # 反自动化指纹 + 稳定性参数
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ] + list(self.extra_args)
        if self.headless:
            args.append("--headless=new")
        kwargs: dict = dict(
            user_data_dir=user_data_dir,
            headless=False,  # 恒 False：无头由 --headless=new 控制，确保用完整 chromium
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
            user_agent=self.user_agent,
            locale="en-US",
            args=args,
        )
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return self._playwright.chromium.launch_persistent_context(**kwargs)

    def stop(self) -> None:
        """关闭 playwright，释放资源。"""
        if self._playwright is not None:
            try:
                self._playwright.stop()
            finally:
                self._playwright = None
