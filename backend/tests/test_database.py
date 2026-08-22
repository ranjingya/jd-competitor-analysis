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
            database = Database(Path(temp_dir) / "data.db")
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
                report_columns = {
                    row["name"]: row
                    for row in connection.execute("PRAGMA table_info(reports)")
                }
                task_columns = {
                    row["name"]: row
                    for row in connection.execute("PRAGMA table_info(analysis_tasks)")
                }
                dataset_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(analysis_datasets)")
                }

        self.assertEqual(tables, {"analysis_datasets", "analysis_tasks", "reports"})
        self.assertEqual(
            {row["table"] for row in foreign_keys},
            {"reports"},
        )
        self.assertTrue({"granularity", "start_date", "end_date"}.issubset(report_columns))
        self.assertNotIn("report_json", report_columns)
        self.assertNotIn("payload_json", dataset_columns)
        self.assertTrue(
            {
                "self_product_json",
                "core_metrics_json",
                "traffic_sources_json",
                "traffic_keywords_json",
                "customer_profile_json",
                "promotion_json",
            }.issubset(dataset_columns)
        )
        self.assertEqual(report_columns["dataset_id"]["notnull"], 0)
        self.assertNotIn("dataset_id", task_columns)
        self.assertTrue(
            {"report_id", "model", "analysis_version", "prompt_hash"}.issubset(task_columns)
        )

    def test_initialize_is_idempotent(self) -> None:
        """重复初始化当前数据库结构不应改变已有表。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "data.db"
            database = Database(database_path)
            database.initialize()
            database.initialize()
            with database.connection() as connection:
                table_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table'"
                ).fetchone()["count"]

        self.assertEqual(table_count, 3)

    def test_legacy_database_is_rejected(self) -> None:
        """旧结构数据库应被拒绝，避免在原文件上静默改表。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "backend.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    "CREATE TABLE analysis_datasets (dataset_id TEXT PRIMARY KEY, payload_json TEXT)"
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(RuntimeError, "请使用新的 data.db"):
                Database(database_path).initialize()


if __name__ == "__main__":
    unittest.main()
