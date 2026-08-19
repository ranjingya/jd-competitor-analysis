"""构造 API 使用的数据仓库。"""

from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from ..database import Database
from ..repositories.report_repository import ReportRepository


@lru_cache(maxsize=1)
def get_database() -> Database:
    """返回共享统一数据库。"""

    return Database(get_settings().database_path)


@lru_cache(maxsize=1)
def get_report_repository() -> ReportRepository:
    """返回共享报告仓库。"""

    return ReportRepository(get_database())
