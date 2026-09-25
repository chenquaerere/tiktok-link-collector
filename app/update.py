"""版本检查与更新（GitHub Releases / 通用 JSON 双源）。

更新源两种形态：
1. GitHub Releases：填仓库 owner/repo，程序自动请求官方 API
   `https://api.github.com/repos/{repo}/releases/latest`，从返回的
   tag_name / body / assets[0].browser_download_url 提取版本信息。
2. 通用 JSON：自定义 URL 返回 `{"version": "...", "url": "...", "notes": "..."}`。

全程静默失败，不影响启动与使用。
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Optional

GITHUB_API_TEMPLATE = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass
class UpdateInfo:
    """一条可用的更新信息。"""

    version: str   # 最新版本号（可能带 v 前缀）
    url: str       # 下载地址（资产直链，无资产时回退到 release 页面）
    notes: str     # 更新说明
    source: str    # "github" | "json"


def github_latest_url(repo: str) -> str:
    """由 owner/repo 生成 GitHub latest release API 地址。"""
    return GITHUB_API_TEMPLATE.format(repo=repo.strip().strip("/"))


def _parse_version(v: str):
    """把版本号拆成可比较的元组，支持 0.1.0 / v0.1.0 / 0.1.0-beta。"""
    v = str(v or "").strip().lstrip("vV")
    m = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", v)
    if not m:
        return (0, 0, 0, v)  # 非数字开头，退化为按剩余字符串比较
    core = tuple(int(x) if x else 0 for x in m.groups())
    pre = v[m.end():].lstrip("-")
    return core + (pre,)


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新（语义化版本，忽略 v 前缀）。"""
    return _parse_version(latest) > _parse_version(current)


def _parse_github(data: dict) -> Optional[UpdateInfo]:
    """从 GitHub Releases API 响应提取更新信息。"""
    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    if not tag:
        return None
    url = ""
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        u = str(asset.get("browser_download_url") or "")
        if u:
            url = u
            break
    if not url:
        url = str(data.get("html_url") or "")
    return UpdateInfo(
        version=tag,
        url=url,
        notes=str(data.get("body") or "").strip(),
        source="github",
    )


def check_update(update_url: str, current_version: str,
                 timeout: int = 10) -> Optional[UpdateInfo]:
    """检查更新。返回 UpdateInfo 或 None（无源 / 失败 / 已是最新）。"""
    if not update_url:
        return None
    try:
        req = urllib.request.Request(update_url, headers={
            "User-Agent": "TikTokLinkCollector",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    # 区分 GitHub Releases 与通用 JSON：GitHub 响应含 tag_name/assets 字段
    if "tag_name" in data or ("assets" in data and "html_url" in data):
        info = _parse_github(data)
    else:
        ver = str(data.get("version", "")).strip()
        if not ver:
            return None
        info = UpdateInfo(
            version=ver,
            url=str(data.get("url", "")),
            notes=str(data.get("notes", "")),
            source="json",
        )

    if info is None:
        return None
    if not is_newer(info.version, current_version):
        return None
    return info
