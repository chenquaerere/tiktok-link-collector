"""账号地区分类：地区常量 + 显示名/解析工具。

设计要点
--------
- 地区是账号的**单值属性**（一个账号归属一个地区），持久化在 `accounts.region`。
- 预置一批东南亚常用地区（本项目账号主要分布区），同时允许自定义：
  「设置地区」弹窗支持直接输入新地区名，界面下拉会自动收录库中已出现过的值。
- 下拉显示名统一为「地区 · @用户名」；账号**没有地区时只显示 @用户名**，
  保持与旧版本一致的观感。凡是需要按显示文本反查账号的页面，
  一律用 `account_id_from_label()` 反解，不要自己写 `lstrip("@")`。
"""
from __future__ import annotations

from typing import Any, List

# 预置地区（顺序即下拉框显示顺序）
REGIONS: List[str] = [
    "越南",
    "缅甸",
    "泰国",
    "印度尼西亚",
    "菲律宾",
    "马来西亚",
    "新加坡",
    "柬埔寨",
    "老挝",
]

# region 为空时的展示名（仅用于显示，不写库）
REGION_NONE = "未分类"

# 筛选下拉的「不筛选」项（账号管理页 / 采集任务页共用）
REGION_FILTER_ALL = "全部地区"

# 显示名分隔符（account_label / account_id_from_label 必须一致）
REGION_SEP = " · "


def normalize_region(value: Any) -> str:
    """清洗地区输入：去首尾空白；「未分类」等占位值统一存为空串。"""
    s = str(value or "").strip()
    if s in (REGION_NONE, "-", "—", "无", "全部", "全部地区"):
        return ""
    return s


def region_display(value: Any) -> str:
    """地区显示名（空值显示为「未分类」）。"""
    return normalize_region(value) or REGION_NONE


def region_options(used: Any = None) -> List[str]:
    """下拉选项 = 预置地区 ∪ 库中已用的自定义地区（去重、保持顺序）。"""
    out = list(REGIONS)
    for r in (used or []):
        name = normalize_region(r)
        if name and name not in out:
            out.append(name)
    return out


def account_label(row: Any) -> str:
    """账号下拉显示名：「越南 · @user」；无地区时即「@user」。"""
    username = _field(row, "username")
    region = normalize_region(_field(row, "region"))
    base = f"@{username}"
    return f"{region}{REGION_SEP}{base}" if region else base


def account_id_from_label(label: str) -> str:
    """从显示名反解 account_id。

    兼容「越南 · @user」「@user」「user」三种形态；
    占位文案（如「（无账号）」）返回空串。
    """
    s = (label or "").strip()
    if not s or s in ("（无账号）", "全部账号"):
        return ""
    sep = REGION_SEP.strip()
    if sep and sep in s:
        s = s.split(sep)[-1]
    return s.strip().lstrip("@")


def _field(row: Any, key: str, default: Any = "") -> Any:
    """兼容 sqlite3.Row 与 dict 取值。"""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default
