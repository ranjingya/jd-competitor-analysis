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

        功能说明：创建标准化数据集、AI 执行记录、报告表及必要索引；已有数据库执行兼容迁移。
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
                    dataset_id TEXT NOT NULL UNIQUE
                        REFERENCES analysis_datasets(dataset_id) ON DELETE CASCADE,
                    report_date TEXT NOT NULL,
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
                    dataset_id TEXT NOT NULL
                        REFERENCES analysis_datasets(dataset_id) ON DELETE CASCADE,
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
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._migrate_task_and_report_schema(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            connection.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_datasets_source_hash
                ON analysis_datasets(source_hash);

                CREATE INDEX IF NOT EXISTS idx_analysis_datasets_pair_date
                ON analysis_datasets(report_date, self_spu, competitor_spu, created_at);

                DROP INDEX IF EXISTS idx_analysis_tasks_source_hash;

                DROP INDEX IF EXISTS idx_reports_dataset;

                CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status_created
                ON analysis_tasks(status, created_at);

                CREATE INDEX IF NOT EXISTS idx_analysis_tasks_dataset
                ON analysis_tasks(dataset_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_analysis_tasks_report_created
                ON analysis_tasks(report_id, created_at);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_tasks_current_report
                ON analysis_tasks(report_id) WHERE status <> 'expired';

                CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_business_key
                ON reports(report_date, self_spu, competitor_spu);

                CREATE INDEX IF NOT EXISTS idx_reports_status_updated
                ON reports(status, updated_at);
                """
            )
        LOGGER.info(
            "Backend 数据库初始化完成：%s，耗时=%.3fs",
            self.path,
            perf_counter() - started_at,
        )

    @staticmethod
    def _column_names(connection: sqlite3.Connection, table_name: str) -> set[str]:
        """返回指定表的字段名集合。"""

        return {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})")
        }

    @staticmethod
    def _execute_migration_script(connection: sqlite3.Connection, script: str) -> None:
        """在当前事务中逐条执行不含内嵌分号的迁移 SQL。"""

        for statement in script.split(";"):
            normalized = statement.strip()
            if normalized:
                connection.execute(normalized)

    def _migrate_task_and_report_schema(self, connection: sqlite3.Connection) -> None:
        """迁移报告业务键和任务当前版本关系。

        功能说明：为旧数据库补充报告业务键和任务报告关联，合并同一日期商品对的重复报告，并将较旧任务标记为 expired。
        参数 connection：当前数据库连接。
        返回值：无；迁移在当前数据库中原地完成。
        """

        report_columns = self._column_names(connection, "reports")
        task_columns = self._column_names(connection, "analysis_tasks")
        if not {"report_date", "self_spu", "competitor_spu"}.issubset(
            report_columns
        ) or "report_id" not in task_columns:
            self._rebuild_legacy_task_and_report_tables(connection)
            task_columns = self._column_names(connection, "analysis_tasks")
        if "model" not in task_columns or {
            "worker_id",
            "lease_token",
            "lease_expires_at",
        }.intersection(task_columns):
            self._rebuild_internal_ai_task_table(connection)

        duplicate_reports = connection.execute(
            """
            SELECT report_date, self_spu, competitor_spu
            FROM reports
            GROUP BY report_date, self_spu, competitor_spu
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for business_key in duplicate_reports:
            reports = connection.execute(
                """
                SELECT report_id, dataset_id
                FROM reports
                WHERE report_date = ? AND self_spu = ? AND competitor_spu = ?
                ORDER BY updated_at DESC, report_id DESC
                """,
                tuple(business_key),
            ).fetchall()
            current_report = reports[0]
            for stale_report in reports[1:]:
                connection.execute(
                    "UPDATE analysis_tasks SET report_id = ? WHERE report_id = ? OR dataset_id = ?",
                    (
                        current_report["report_id"],
                        stale_report["report_id"],
                        stale_report["dataset_id"],
                    ),
                )
                connection.execute(
                    "DELETE FROM reports WHERE report_id = ?",
                    (stale_report["report_id"],),
                )

        missing_links = connection.execute(
            "SELECT COUNT(*) AS count FROM analysis_tasks WHERE report_id IS NULL"
        ).fetchone()["count"]
        if missing_links:
            raise RuntimeError(f"存在 {missing_links} 条无法关联报告的 AI 任务")

        now = utc_now_text()
        report_ids = connection.execute(
            """
            SELECT report_id
            FROM analysis_tasks
            WHERE status <> 'expired'
            GROUP BY report_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for report_row in report_ids:
            tasks = connection.execute(
                """
                SELECT analysis_id
                FROM analysis_tasks
                WHERE report_id = ? AND status <> 'expired'
                ORDER BY created_at DESC, analysis_id DESC
                """,
                (report_row["report_id"],),
            ).fetchall()
            stale_task_ids = [task["analysis_id"] for task in tasks[1:]]
            connection.executemany(
                """
                UPDATE analysis_tasks
                SET status = 'expired', updated_at = ?
                WHERE analysis_id = ?
                """,
                [(now, analysis_id) for analysis_id in stale_task_ids],
            )
            LOGGER.info(
                "历史 AI 任务已标记过期：report_id=%s，count=%s",
                report_row["report_id"],
                len(stale_task_ids),
            )

    @staticmethod
    def _rebuild_legacy_task_and_report_tables(connection: sqlite3.Connection) -> None:
        """将旧报告和任务表重建为当前结构。

        功能说明：按日期和商品对保留最近报告，为全部历史任务补充报告关联，并建立真实的非空字段和外键约束。
        参数 connection：当前数据库连接。
        返回值：无。
        """

        Database._execute_migration_script(
            connection,
            """
            CREATE TABLE reports_migrated (
                report_id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL UNIQUE
                    REFERENCES analysis_datasets(dataset_id) ON DELETE CASCADE,
                report_date TEXT NOT NULL,
                self_spu TEXT NOT NULL,
                competitor_spu TEXT NOT NULL,
                status TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            INSERT INTO reports_migrated (
                report_id, dataset_id, report_date, self_spu, competitor_spu,
                status, report_json, created_at, updated_at
            )
            SELECT
                report_id, dataset_id, report_date, self_spu, competitor_spu,
                status, report_json, created_at, updated_at
            FROM (
                SELECT
                    report.report_id,
                    report.dataset_id,
                    dataset.report_date,
                    dataset.self_spu,
                    dataset.competitor_spu,
                    report.status,
                    report.report_json,
                    report.created_at,
                    report.updated_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY dataset.report_date, dataset.self_spu, dataset.competitor_spu
                        ORDER BY report.updated_at DESC, report.report_id DESC
                    ) AS business_rank
                FROM reports AS report
                JOIN analysis_datasets AS dataset ON dataset.dataset_id = report.dataset_id
            )
            WHERE business_rank = 1;

            CREATE TABLE analysis_tasks_migrated (
                analysis_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL
                    REFERENCES reports_migrated(report_id) ON DELETE CASCADE,
                dataset_id TEXT NOT NULL
                    REFERENCES analysis_datasets(dataset_id) ON DELETE CASCADE,
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

            INSERT INTO analysis_tasks_migrated (
                analysis_id, report_id, dataset_id, model, source_hash, payload_json,
                result_json, status,
                attempt_count, error_message, created_at, updated_at, completed_at
            )
            SELECT
                task.analysis_id,
                report.report_id,
                task.dataset_id,
                'codex-mac',
                task.source_hash,
                task.payload_json,
                task.result_json,
                CASE
                    WHEN task.status IN ('pending', 'processing') THEN 'failed'
                    ELSE task.status
                END,
                task.attempt_count,
                CASE
                    WHEN task.status IN ('pending', 'processing')
                    THEN COALESCE(task.error_message, '架构迁移时终止的旧 AI 任务')
                    ELSE task.error_message
                END,
                task.created_at,
                task.updated_at,
                task.completed_at
            FROM analysis_tasks AS task
            JOIN analysis_datasets AS dataset ON dataset.dataset_id = task.dataset_id
            JOIN reports_migrated AS report
              ON report.report_date = dataset.report_date
             AND report.self_spu = dataset.self_spu
             AND report.competitor_spu = dataset.competitor_spu;
            """,
        )
        original_count = connection.execute(
            "SELECT COUNT(*) AS count FROM analysis_tasks"
        ).fetchone()["count"]
        migrated_count = connection.execute(
            "SELECT COUNT(*) AS count FROM analysis_tasks_migrated"
        ).fetchone()["count"]
        if migrated_count != original_count:
            raise RuntimeError("存在无法关联唯一报告的历史 AI 任务")
        Database._execute_migration_script(
            connection,
            """
            DROP TABLE analysis_tasks;
            DROP TABLE reports;
            ALTER TABLE reports_migrated RENAME TO reports;
            ALTER TABLE analysis_tasks_migrated RENAME TO analysis_tasks;
            """,
        )

    @staticmethod
    def _rebuild_internal_ai_task_table(connection: sqlite3.Connection) -> None:
        """将 Mac Worker 任务表迁移为后端内部 AI 执行记录。

        功能说明：保留历史输入、结果和状态，补充模型标识；迁移时仍在等待或处理的任务标记为 failed，供后端下次运行重试。
        参数 connection：当前数据库连接。
        返回值：无。
        """

        Database._execute_migration_script(
            connection,
            """
            CREATE TABLE analysis_tasks_migrated (
                analysis_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL
                    REFERENCES reports(report_id) ON DELETE CASCADE,
                dataset_id TEXT NOT NULL
                    REFERENCES analysis_datasets(dataset_id) ON DELETE CASCADE,
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

            INSERT INTO analysis_tasks_migrated (
                analysis_id, report_id, dataset_id, model, source_hash,
                payload_json, result_json, status, attempt_count, error_message,
                created_at, updated_at, completed_at
            )
            SELECT
                analysis_id, report_id, dataset_id, 'codex-mac', source_hash,
                payload_json, result_json,
                CASE
                    WHEN status IN ('pending', 'processing') THEN 'failed'
                    ELSE status
                END,
                attempt_count,
                CASE
                    WHEN status IN ('pending', 'processing')
                    THEN COALESCE(error_message, '架构迁移时终止的旧 AI 任务')
                    ELSE error_message
                END,
                created_at, updated_at, completed_at
            FROM analysis_tasks;

            DROP TABLE analysis_tasks;
            ALTER TABLE analysis_tasks_migrated RENAME TO analysis_tasks;
            """,
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
