"""系统提示音通知（采集完成/失败时提醒，不弹窗、不打断操作）。

- Windows：winsound.MessageBeep（成功=信息音，失败=警告音）
- macOS：afplay 播放系统音
- 其它：终端响铃（静默降级）
"""
from __future__ import annotations

import sys


def _beep(kind: str = "info") -> None:
    try:
        if sys.platform == "win32":
            import winsound
            winsound.MessageBeep(0x40 if kind == "info" else 0x10)  # info / error
        elif sys.platform == "darwin":
            import subprocess
            sound = ("/System/Library/Sounds/Glass.aiff" if kind == "info"
                     else "/System/Library/Sounds/Sosumi.aiff")
            subprocess.run(["afplay", sound], timeout=2)
        else:
            print("\a", end="", flush=True)
    except Exception:
        pass


def notify_success() -> None:
    """采集完成/成功提示。"""
    _beep("info")


def notify_failure() -> None:
    """采集失败/出错提示。"""
    _beep("error")
