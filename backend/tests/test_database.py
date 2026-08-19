"""测试 Backend 统一数据库初始化。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import Database


class DatabaseTest(unittest.TestCase):
    """验证三张表、索引和外键设置。"""

    def test_initialize_creates_three_tables(self) -> None:
        """统一数据库初始化应创建且只依赖三张业务表。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "backend.db")
            database.initialize()
            with database.connection() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                foreign_keys = connection.execute(
                    "PRAGMA foreign_key_list(analysis_tasks)"
                ).fetchall()

        self.assertEqual(tables, {"analysis_datasets", "analysis_tasks", "reports"})
        self.assertEqual(
            {row["table"] for row in foreign_keys},
            {"analysis_datasets", "reports"},
        )

    def test_initialize_migrates_old_tasks_to_single_current_task(self) -> None:
        """旧数据库升级时应补充报告关联，并将较旧任务标记为 expired。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "backend.db"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE analysis_datasets (
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
                CREATE TABLE analysis_tasks (
                    analysis_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    status TEXT NOT NULL,
                    worker_id TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE reports (
                    report_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO analysis_datasets VALUES (
                    'dataset-1', '2026-08-17', '10001', '20001', '10001+20001',
                    'dataset-hash', '{}', 'ready', '2026-08-19T05:00:00+00:00'
                );
                INSERT INTO reports VALUES (
                    'report-1', 'dataset-1', 'ready', '{}',
                    '2026-08-19T05:00:00+00:00', '2026-08-19T07:00:00+00:00'
                );
                INSERT INTO analysis_tasks VALUES (
                    'task-old', 'dataset-1', 'old-hash', '{}', '{}', 'completed',
                    'mac', NULL, NULL, 1, NULL,
                    '2026-08-19T05:00:00+00:00', '2026-08-19T06:00:00+00:00',
                    '2026-08-19T06:00:00+00:00'
                );
                INSERT INTO analysis_tasks VALUES (
                    'task-new', 'dataset-1', 'new-hash', '{}', '{}', 'completed',
                    'mac', NULL, NULL, 1, NULL,
                    '2026-08-19T07:00:00+00:00', '2026-08-19T08:00:00+00:00',
                    '2026-08-19T08:00:00+00:00'
                );
                """
            )
            connection.close()

            database = Database(database_path)
            database.initialize()
            with database.connection() as migrated:
                report = migrated.execute(
                    "SELECT report_date, self_spu, competitor_spu FROM reports"
                ).fetchone()
                tasks = migrated.execute(
                    "SELECT analysis_id, report_id, model, status FROM analysis_tasks ORDER BY analysis_id"
                ).fetchall()
                task_columns = {
                    row["name"] for row in migrated.execute("PRAGMA table_info(analysis_tasks)")
                }

        self.assertEqual(tuple(report), ("2026-08-17", "10001", "20001"))
        self.assertEqual(
            [tuple(row) for row in tasks],
            [
                ("task-new", "report-1", "codex-mac", "completed"),
                ("task-old", "report-1", "codex-mac", "expired"),
            ],
        )
        self.assertNotIn("lease_token", task_columns)
        self.assertNotIn("worker_id", task_columns)


if __name__ == "__main__":
    unittest.main()
