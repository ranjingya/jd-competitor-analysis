"""加载后端运行配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def _positive_integer(name: str, default: int) -> int:
    """读取正整数环境变量。"""

    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} 必须是正整数：{raw_value}") from error
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0：{value}")
    return value


@dataclass(frozen=True)
class Settings:
    """保存后端运行参数。"""

    database_path: Path
    ai_worker_token: str | None
    task_lease_seconds: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载后端配置。

    功能说明：加载项目根目录 `.env` 与进程环境变量，解析报告目录、任务数据库和 Worker 鉴权参数。
    返回值：完成基础校验的后端配置对象。
    """

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    database_path = Path(
        os.getenv("BACKEND_DATABASE_PATH", str(PROJECT_ROOT / "data" / "backend.db"))
    ).expanduser().resolve()
    token = os.getenv("AI_WORKER_TOKEN", "").strip() or None
    return Settings(
        database_path=database_path,
        ai_worker_token=token,
        task_lease_seconds=_positive_integer("TASK_LEASE_SECONDS", 1800),
    )
