"""PyInstaller 打包脚本：生成 Windows 可执行程序（onedir 目录模式）。

用法（在 ui310 venv 下执行）：
    python build.py

产物：
    dist/TikTokLinkCollector/TikTokLinkCollector.exe
    （便携版：整个 dist/TikTokLinkCollector 目录可复制到任意位置运行）

说明：
- 采用 onedir 而非 onefile：customtkinter + playwright + tkinter 依赖较多，
  目录模式启动更快、更稳定、报错更易排查。
- 浏览器内核（chromium 等）由 post-build 步骤从 %LOCALAPPDATA%/ms-playwright
  复制进 dist 的 playwright driver .local-browsers 目录，实现零依赖便携。
  （frozen 环境下 playwright 会从 driver/package/.local-browsers 找浏览器，
  而不是 %LOCALAPPDATA%/ms-playwright，缺内核会导致所有账号采集失败）
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "TikTokLinkCollector"

# 需要随包分发的 playwright 浏览器内核（与 playwright 1.63.0 匹配）
BROWSER_BUILDS = [
    "chromium-1243",
    "chromium_headless_shell-1243",
    "ffmpeg-1011",
]


def _ms_playwright_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"


def bundle_browsers() -> None:
    """把 playwright 浏览器内核放进 dist 的 .local-browsers（幂等）。

    优先从 `.local-browsers_tmp` 临时目录移动（同盘、秒级），否则从
    %LOCALAPPDATA%/ms-playwright 复制。这样重复打包时无需重拷内核。
    """
    tmp_root = ROOT / ".local-browsers_tmp"
    use_tmp = tmp_root.exists()
    src_root = tmp_root if use_tmp else _ms_playwright_dir()
    dest_root = (
        ROOT / "dist" / APP_NAME / "_internal" / "playwright" / "driver"
        / "package" / ".local-browsers"
    )
    if not src_root.exists():
        print(f"[WARN] 未找到浏览器内核源目录：{src_root}，跳过内核打包")
        return
    dest_root.mkdir(parents=True, exist_ok=True)
    for name in BROWSER_BUILDS:
        src = src_root / name
        dest = dest_root / name
        if not src.exists():
            print(f"[WARN] 缺少内核 {name}，跳过")
            continue
        if dest.exists():
            print(f"[SKIP] {name} 已存在")
            continue
        print(f"[{'MOVE' if use_tmp else 'COPY'}] {name} ...")
        if use_tmp:
            shutil.move(str(src), str(dest))
        else:
            shutil.copytree(src, dest)
    # 清理已搬空的临时目录
    if use_tmp:
        try:
            tmp_root.rmdir()
        except OSError:
            pass
    print("[OK] 浏览器内核打包完成")


def clean() -> None:
    for d in ("build", "dist"):
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for spec in ROOT.glob("*.spec"):
        spec.unlink(missing_ok=True)


def build() -> None:
    import PyInstaller.__main__ as pyi

    args = [
        str(ROOT / "main.py"),
        "--name", APP_NAME,
        "--onedir",
        "--windowed",            # 无控制台窗口（日志写文件）
        "--noconfirm",
        "--clean",
        "--noupx",
        # 打包数据/依赖
        "--collect-all", "customtkinter",
        "--collect-all", "playwright",
        "--collect-data", "tzdata",
        # 排除测试与开发依赖，减小体积
        "--exclude-module", "pytest",
        "--exclude-module", "unittest",
        "--exclude-module", "tests",
        "--exclude-module", "mocks",
    ]
    pyi.run(args)
    print(f"\n[OK] 打包完成：{ROOT / 'dist' / APP_NAME / (APP_NAME + '.exe')}")
    bundle_browsers()


if __name__ == "__main__":
    if "--clean-only" in sys.argv:
        clean()
        print("[OK] 已清理 build/dist")
    elif "--bundle-browsers-only" in sys.argv:
        bundle_browsers()
    else:
        clean()
        build()
