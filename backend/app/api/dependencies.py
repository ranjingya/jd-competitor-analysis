"""构造 API 使用的数据仓库。"""

from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from ..repositories.report_repository import ReportRepository
from ..repositories.task_repository import TaskRepository


@lru_cache(maxsize=1)
def get_report_repository() -> ReportRepository:
    """返回共享报告仓库。"""

    return ReportRepository(get_settings().reports_dir)


@lru_cache(maxsize=1)
def get_task_repository() -> TaskRepository:
    """返回共享任务仓库。"""

    return TaskRepository(get_settings().task_database_path)
