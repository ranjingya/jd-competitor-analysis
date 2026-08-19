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

        self.assertEqual(tables, {"analysis_datasets", "analysis_tasks", "reports"})
        self.assertEqual(foreign_keys[0]["table"], "analysis_datasets")


if __name__ == "__main__":
    unittest.main()
