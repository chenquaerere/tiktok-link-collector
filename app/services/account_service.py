"""账号管理服务层（P3）。

- parse_profile_url：从多种输入（完整主页 URL / @handle / 裸用户名）解析出
  username 与规范化的 profile_url，兼容 TikTok 各种 URL 形态。
- AccountService：账号增删改查、启停、批量导入（容错：个别错误不阻断整体）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.core import regions as region_util
from app.core.models import Account
from app.db.database import Database

# TikTok 主页 URL 形态：
#   https://www.tiktok.com/@username
#   https://www.tiktok.com/@username?lang=en
#   https://vm.tiktok.com/xxx  （短链，无法直接得 username，标记失败）
#   仅 @username 或 username
_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?tiktok\.com/@(?P<user>[A-Za-z0-9._-]+)/?",
    re.IGNORECASE,
)
_HANDLE_RE = re.compile(r"^@?(?P<user>[A-Za-z0-9._-]{1,30})$")
_VALID_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,30}$")


@dataclass
class ParseResult:
    ok: bool
    username: str = ""
    profile_url: str = ""
    error: str = ""


def parse_profile_url(raw: str) -> ParseResult:
    """解析一个账号输入，返回标准化结果。失败时 ok=False 且带 error 原因。"""
    raw = (raw or "").strip()
    if not raw:
        return ParseResult(False, error="空输入")

    # 1) 完整 URL
    m = _URL_RE.search(raw)
    if m:
        username = m.group("user")
        return ParseResult(True, username=username,
                           profile_url=f"https://www.tiktok.com/@{username}")

    # 2) 含 tiktok.com 但没匹配到 @user（短链等）
    if "tiktok.com" in raw.lower():
        return ParseResult(False, error=f"无法从该链接解析用户名: {raw[:60]}")

    # 3) @handle 或裸用户名
    m = _HANDLE_RE.match(raw)
    if m:
        username = m.group("user")
        if _VALID_USERNAME_RE.match(username):
            return ParseResult(True, username=username,
                               profile_url=f"https://www.tiktok.com/@{username}")
        return ParseResult(False, error=f"用户名格式非法: {raw[:60]}")

    return ParseResult(False, error=f"无法识别该账号输入: {raw[:60]}")


def _row_region(row) -> str:
    """读取行里的地区（兼容未加列的历史库 / dict 行）。"""
    try:
        return row["region"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


class AccountService:
    """账号池管理。"""

    def __init__(self, db: Database):
        self.db = db

    # ---- 单个 ----
    def add(self, raw: str, collect_count: int = 4, remark: str = "",
            region: str = "") -> Tuple[bool, str]:
        """解析并新增账号。返回 (是否成功, 消息)。"""
        pr = parse_profile_url(raw)
        if not pr.ok:
            return False, pr.error
        account = Account(
            account_id=pr.username,
            username=pr.username,
            profile_url=pr.profile_url,
            collect_count=collect_count,
            remark=remark,
            region=region_util.normalize_region(region),
        )
        inserted = self.db.insert_account(account)
        if inserted:
            tag = region_util.region_display(region)
            suffix = f"（{tag}）" if region_util.normalize_region(region) else ""
            return True, f"已添加 @{pr.username}{suffix}"
        return False, f"账号 @{pr.username} 已存在"

    def update(self, account_id: str, *, display_name: Optional[str] = None,
               remark: Optional[str] = None, collect_count: Optional[int] = None,
               enabled: Optional[bool] = None,
               region: Optional[str] = None) -> bool:
        row = self.db.get_account(account_id)
        if not row:
            return False
        acc = Account(
            account_id=row["account_id"],
            username=row["username"],
            profile_url=row["profile_url"],
            display_name=display_name if display_name is not None else row["display_name"],
            remark=remark if remark is not None else row["remark"],
            enabled=enabled if enabled is not None else bool(row["enabled"]),
            login_status=row["login_status"],
            collect_count=collect_count if collect_count is not None else row["collect_count"],
            # ⚠️ region 必须显式回填：update_account 是「整行覆盖」式的 UPDATE，
            #    漏了它会把已有地区写成空串（改采集数量时地区被清空的坑）。
            region=(region_util.normalize_region(region) if region is not None
                    else _row_region(row)),
        )
        self.db.update_account(acc)
        return True

    def delete(self, account_id: str) -> bool:
        return self.db.delete_account(account_id)

    def set_enabled(self, account_id: str, enabled: bool) -> bool:
        return self.db.set_account_enabled(account_id, enabled)

    # ---- 批量 ----
    def import_many(self, raws: List[str], collect_count: int = 4,
                    region: str = "") -> dict:
        """批量导入账号。逐个解析，个别错误不阻断整体。

        region 会应用到本批全部新账号（之后的批量「设置地区」仍可改）。
        返回：{"imported": [...], "failed": [...], "skipped": [...]}
        """
        result = {"imported": [], "failed": [], "skipped": []}
        seen = set()
        region_clean = region_util.normalize_region(region)
        for raw in raws:
            raw = (raw or "").strip()
            if not raw:
                continue
            pr = parse_profile_url(raw)
            if not pr.ok:
                result["failed"].append({"input": raw, "error": pr.error})
                continue
            if pr.username in seen:
                result["skipped"].append({"input": raw, "username": pr.username,
                                          "reason": "本次导入内重复"})
                continue
            seen.add(pr.username)
            account = Account(
                account_id=pr.username, username=pr.username,
                profile_url=pr.profile_url, collect_count=collect_count,
                region=region_clean,
            )
            if self.db.insert_account(account):
                result["imported"].append(pr.username)
            else:
                result["skipped"].append({"input": raw, "username": pr.username,
                                          "reason": "数据库中已存在"})
        return result

    # ---- 地区分类 ----
    def set_regions(self, account_ids: List[str], region: str) -> int:
        """批量设置地区（传空串 = 取消分类）。返回受影响账号数。"""
        return self.db.set_account_regions(account_ids,
                                           region_util.normalize_region(region))

    def region_options(self) -> List[str]:
        """地区下拉选项 = 预置地区 ∪ 库中出现过的自定义地区。"""
        return region_util.region_options(self.db.used_regions())

    def region_stats(self, enabled_only: bool = False) -> List[tuple]:
        """地区统计：[(地区显示名, 数量), ...]（空地区显示为「未分类」）。"""
        return [(region_util.region_display(name), n)
                for name, n in self.db.region_stats(enabled_only)]

    def used_regions(self) -> List[str]:
        return self.db.used_regions()

    # ---- 查询 ----
    def list(self, enabled_only: bool = False):
        return self.db.list_accounts(enabled_only=enabled_only)

    def get(self, account_id: str):
        return self.db.get_account(account_id)
