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
    analysis_lock_path: Path
    deepseek_api_key: str | None
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: int
    deepseek_max_attempts: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """加载后端配置。

    功能说明：加载项目根目录 `.env` 与进程环境变量，解析统一数据库、任务锁和 DeepSeek 参数。
    返回值：完成基础校验的后端配置对象。
    """

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    database_path = Path(
        os.getenv("BACKEND_DATABASE_PATH", str(PROJECT_ROOT / "data" / "data.db"))
    ).expanduser().resolve()
    lock_value = os.getenv("ANALYSIS_LOCK_PATH", "").strip()
    lock_path = Path(
        lock_value or database_path.parent / "warehouse-daily-run.lock"
    ).expanduser().resolve()
    return Settings(
        database_path=database_path,
        analysis_lock_path=lock_path,
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip() or None,
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro").strip(),
        deepseek_timeout_seconds=_positive_integer("DEEPSEEK_TIMEOUT_SECONDS", 300),
        deepseek_max_attempts=_positive_integer("DEEPSEEK_MAX_ATTEMPTS", 2),
    )
