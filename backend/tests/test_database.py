"""测试 Backend 统一数据库初始化。"""

from __future__ import annotations

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
                report_columns = {
                    row["name"]: row
                    for row in connection.execute("PRAGMA table_info(reports)")
                }
                task_columns = {
                    row["name"]: row
                    for row in connection.execute("PRAGMA table_info(analysis_tasks)")
                }

        self.assertEqual(tables, {"analysis_datasets", "analysis_tasks", "reports"})
        self.assertEqual(
            {row["table"] for row in foreign_keys},
            {"analysis_datasets", "reports"},
        )
        self.assertTrue({"granularity", "start_date", "end_date"}.issubset(report_columns))
        self.assertEqual(report_columns["dataset_id"]["notnull"], 0)
        self.assertEqual(task_columns["dataset_id"]["notnull"], 0)

    def test_initialize_is_idempotent(self) -> None:
        """重复初始化当前数据库结构不应改变已有表。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "backend.db"
            database = Database(database_path)
            database.initialize()
            database.initialize()
            with database.connection() as connection:
                table_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table'"
                ).fetchone()["count"]

        self.assertEqual(table_count, 3)


if __name__ == "__main__":
    unittest.main()
