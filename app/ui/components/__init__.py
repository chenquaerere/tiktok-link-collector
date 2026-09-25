"""UI 组件包：Toast / Dialog / EmptyState / LoadingState / PageHeader / StatusBadge。

统一从这里导入，避免页面散落硬编码控件。
"""
from __future__ import annotations

from .toast import Toast, ToastManager
from .dialog import confirm, info, error
from .empty_state import EmptyState
from .loading import LoadingState
from .page_header import PageHeader
from .badge import StatusBadge

__all__ = [
    "Toast", "ToastManager",
    "confirm", "info", "error",
    "EmptyState", "LoadingState", "PageHeader", "StatusBadge",
]
