#!/usr/bin/env python3
"""TikTok 作品链接采集器 —— 程序入口。

用法：
    python main.py            # 启动桌面界面
"""
import sys


def main() -> int:
    from app.app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
