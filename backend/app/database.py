"""管理 Backend 统一 SQLite 数据库连接和三表初始化。"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Iterator


LOGGER = logging.getLogger(__name__)


def utc_now_text() -> str:
    """返回带时区、秒精度的当前 UTC 时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """提供统一 SQLite 数据库连接和初始化能力。"""

    def __init__(self, path: Path) -> None:
        """保存数据库路径。

        功能说明：记录统一 `backend.db` 位置，实际目录和表在初始化时创建。
        参数 path：SQLite 数据库文件路径。
        返回值：无。
        """

        self.path = path

    def initialize(self) -> None:
        """初始化 Backend 三张业务表。

        功能说明：创建日数据集、日周月报告、AI 执行记录及必要索引。
        返回值：无。
        """

        started_at = perf_counter()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS analysis_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    report_date TEXT NOT NULL,
                    self_spu TEXT NOT NULL,
                    competitor_spu TEXT NOT NULL,
                    compare_number TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    dataset_id TEXT UNIQUE
                        REFERENCES analysis_datasets(dataset_id) ON DELETE SET NULL,
                    granularity TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    self_spu TEXT NOT NULL,
                    competitor_spu TEXT NOT NULL,
                    status TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_tasks (
                    analysis_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL
                        REFERENCES reports(report_id) ON DELETE CASCADE,
                    dataset_id TEXT
                        REFERENCES analysis_datasets(dataset_id) ON DELETE SET NULL,
                    model TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_datasets_source_hash
                ON analysis_datasets(source_hash);

                CREATE INDEX IF NOT EXISTS idx_analysis_datasets_pair_date
                ON analysis_datasets(report_date, self_spu, competitor_spu, created_at);

                CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status_created
                ON analysis_tasks(status, created_at);

                CREATE INDEX IF NOT EXISTS idx_analysis_tasks_dataset
                ON analysis_tasks(dataset_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_analysis_tasks_report_created
                ON analysis_tasks(report_id, created_at);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_tasks_current_report
                ON analysis_tasks(report_id) WHERE status <> 'expired';

                CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_business_key
                ON reports(granularity, start_date, end_date, self_spu, competitor_spu);

                CREATE INDEX IF NOT EXISTS idx_reports_status_updated
                ON reports(status, updated_at);
                """
            )
        LOGGER.info(
            "Backend 数据库初始化完成：%s，耗时=%.3fs",
            self.path,
            perf_counter() - started_at,
        )

    def connect(self) -> sqlite3.Connection:
        """创建启用字典行和外键约束的 SQLite 连接。

        功能说明：为 Repository 返回统一连接配置，支持显式事务和外键约束。
        返回值：已配置的 SQLite 连接。
        """

        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """提供退出时必定关闭的数据库连接上下文。

        功能说明：统一管理普通 Repository 操作的连接生命周期，避免 SQLite 连接泄漏。
        返回值：可用于 `with` 语句的 SQLite 连接迭代器。
        """

        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()
