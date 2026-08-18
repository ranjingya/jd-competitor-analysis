"""测试数仓连接配置和只读探测。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text

from jd_competitor_analysis.warehouse import load_warehouse_config, probe_warehouse


class WarehouseTest(unittest.TestCase):
    """验证数仓配置校验、连接探测和安全表名处理。"""

    def test_probe_reads_limited_rows_from_sqlite(self) -> None:
        """探测命令应连接数据库并返回受限样例。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "warehouse.db"
            database_url = f"sqlite+pysqlite:///{database_path}"
            engine = create_engine(database_url)
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE sample_daily (dt TEXT, sku_id TEXT, deal_amount REAL)"))
                connection.execute(
                    text(
                        "INSERT INTO sample_daily (dt, sku_id, deal_amount) "
                        "VALUES ('2026-08-17', '10001', 128.5), ('2026-08-17', '10002', 256.0)"
                    )
                )
            engine.dispose()

            with patch.dict(
                os.environ,
                {
                    "DB_URL": database_url,
                    "DB_DRIVER": "sqlite+pysqlite",
                    "DB_TEST_TABLE": "sample_daily",
                    "DB_TEST_LIMIT": "1",
                },
                clear=False,
            ):
                config = load_warehouse_config(Path(temp_dir) / "missing.env")
                result = probe_warehouse(config)

        self.assertTrue(result["connection_ok"])
        self.assertEqual(result["table"], "sample_daily")
        self.assertEqual(result["columns"], ["dt", "sku_id", "deal_amount"])
        self.assertEqual(len(result["rows"]), 1)

    def test_config_requires_connection_parameters_without_url(self) -> None:
        """未提供完整 URL 时必须包含必要连接参数。"""

        environment = {
            "DB_URL": "",
            "DB_HOST": "",
            "DB_NAME": "",
            "DB_USER": "",
            "DB_PASSWORD": "",
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(ValueError, "数仓连接配置不完整"):
                load_warehouse_config(Path(temp_dir) / "missing.env")

    def test_probe_rejects_unsafe_table_name(self) -> None:
        """测试表名不得携带额外 SQL。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database_url = f"sqlite+pysqlite:///{Path(temp_dir) / 'warehouse.db'}"
            with patch.dict(
                os.environ,
                {
                    "DB_URL": database_url,
                    "DB_DRIVER": "sqlite+pysqlite",
                    "DB_TEST_TABLE": "sample; DROP TABLE sample",
                },
                clear=False,
            ):
                config = load_warehouse_config(Path(temp_dir) / "missing.env")
                with self.assertRaisesRegex(ValueError, "测试表名包含非法字符"):
                    probe_warehouse(config)


if __name__ == "__main__":
    unittest.main()
