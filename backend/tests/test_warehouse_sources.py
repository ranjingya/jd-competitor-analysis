"""测试数仓正式来源读取和商品对解析。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

from jd_competitor_analysis.warehouse_sources import (
    COMPETITOR_TABLES,
    SELF_SKU_TABLE,
    ProductPair,
    normalize_sku_ids,
    read_competitor_sources,
    read_self_sku_daily,
)


class ProductPairTest(unittest.TestCase):
    """验证商品对和 SKU 标识规则。"""

    def test_compare_number_maps_self_and_competitor_spu(self) -> None:
        """加号前后应分别映射为本品 SPU 和竞品 SPU。"""

        pair = ProductPair.parse("100174558585+100112260075")

        self.assertEqual(pair.self_spu, "100174558585")
        self.assertEqual(pair.competitor_spu, "100112260075")
        self.assertEqual(pair.compare_number, "100174558585+100112260075")

    def test_compare_number_rejects_ambiguous_values(self) -> None:
        """缺少一侧或包含多个竞品的编号应被拒绝。"""

        for invalid_value in ("10001", "10001+", "10001+10002+10003", "self+10002", "10001+10001"):
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(ValueError):
                    ProductPair.parse(invalid_value)

    def test_sku_ids_accept_float_display_and_remove_duplicates(self) -> None:
        """数仓浮点展示的 SKU 应转换为唯一整数参数。"""

        self.assertEqual(normalize_sku_ids([5476736.0, "5476736", 10002]), (5476736, 10002))


class WarehouseSourcesTest(unittest.TestCase):
    """验证五张竞品表顺序读取和本品 SKU 最新记录选择。"""

    def setUp(self) -> None:
        """创建包含正式表名的临时 SQLite 数仓。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "warehouse.db"
        self.engine = create_engine(f"sqlite+pysqlite:///{database_path}")
        with self.engine.begin() as connection:
            for table in COMPETITOR_TABLES:
                connection.execute(
                    text(
                        f"CREATE TABLE {table.table_name} ("
                        "id INTEGER, dt TEXT, compare_number TEXT, json_data TEXT, updated_at TEXT)"
                    )
                )
                connection.execute(
                    text(
                        f"INSERT INTO {table.table_name} "
                        "(id, dt, compare_number, json_data, updated_at) VALUES "
                        "(1, '2026-08-11', '10001+20001', '{\"批次\": \"旧\"}', '2026-08-12 01:00:00'), "
                        "(2, '2026-08-11', '10001+20001', '{\"批次\": \"新\"}', '2026-08-12 02:00:00'), "
                        "(4, '2026-08-11', '10001+20001', '{\"批次\": \"新2\"}', '2026-08-12 02:00:00'), "
                        "(3, '2026-08-11', '99999+20001', '{\"批次\": \"其他商品\"}', '2026-08-12 03:00:00')"
                    )
                )
            connection.execute(
                text(
                    f"CREATE TABLE {SELF_SKU_TABLE} ("
                    "dt TEXT, sku_name TEXT, sku_id REAL, brand TEXT, category1 TEXT, category2 TEXT, "
                    "category3 TEXT, shop_name TEXT, business_model TEXT, pv REAL, uv REAL, "
                    "average_pv REAL, average_duration REAL, transaction_user REAL, "
                    "transaction_conversion_rate REAL, transaction_order REAL, transaction_product REAL, "
                    "transaction_amount REAL, transaction_atv REAL, cart_user REAL, "
                    "cart_conversion_rate REAL, cart_product REAL, create_time TEXT, "
                    "time_granularity TEXT, relevant_dt TEXT)"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {SELF_SKU_TABLE} "
                    "(dt, sku_name, sku_id, pv, uv, create_time, time_granularity, relevant_dt) VALUES "
                    "('2026-08-11', 'SKU A 旧', 10001, 10, 5, '2026-08-12 01:00:00', 'natural_day', '2026-08-11'), "
                    "('2026-08-11', 'SKU A 新', 10001, 20, 8, '2026-08-12 02:00:00', 'natural_day', '2026-08-11'), "
                    "('2026-08-11', 'SKU B', 10002, 30, 9, '2026-08-12 01:00:00', 'natural_day', '2026-08-11'), "
                    "('2026-08-11', '月数据', 10002, 999, 999, '2026-08-12 03:00:00', 'natural_month', '2026-08-11')"
                )
            )

    def tearDown(self) -> None:
        """释放临时数仓。"""

        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_competitor_sources_keep_latest_load_for_requested_pair(self) -> None:
        """每张竞品表只应返回请求商品对的最新同步批次。"""

        pair = ProductPair.parse("10001+20001")
        result = read_competitor_sources(self.engine, pair, "2026-08-11")

        self.assertEqual(set(result), {table.source_id for table in COMPETITOR_TABLES})
        for rows in result.values():
            self.assertEqual(len(rows), 2)
            self.assertEqual([row["id"] for row in rows], [2, 4])
            self.assertEqual(rows[0]["self_spu"], "10001")
            self.assertEqual(rows[0]["competitor_spu"], "20001")
            self.assertEqual([row["data"] for row in rows], [{"批次": "新"}, {"批次": "新2"}])

    def test_self_sku_daily_keeps_latest_natural_day_row(self) -> None:
        """本品查询应过滤粒度，并为每个 SKU 选择最新记录。"""

        rows = read_self_sku_daily(self.engine, "2026-08-11", [10001, 10002])

        self.assertEqual([row["sku_id"] for row in rows], ["10001", "10002"])
        self.assertEqual(rows[0]["sku_name"], "SKU A 新")
        self.assertEqual(rows[0]["pv"], 20)
        self.assertEqual(rows[1]["pv"], 30)


if __name__ == "__main__":
    unittest.main()
