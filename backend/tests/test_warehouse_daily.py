"""测试完整标准化日数据的可复用构建入口。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from jd_competitor_analysis.lark_mapping import SkuMapping
from jd_competitor_analysis.warehouse_daily import (
    WarehousePairNoDataError,
    build_daily_dataset,
    count_competitor_source_rows,
)
from jd_competitor_analysis.warehouse_sources import ProductPair


class WarehouseDailyDatasetTest(unittest.TestCase):
    """验证外部来源读取顺序和商品对无数据门槛。"""

    def setUp(self) -> None:
        """准备商品对和映射客户端。"""

        self.pair = ProductPair("10001", "20001")
        self.mapping = SkuMapping("10001", "30001", "69001", "商品 A", "蓝色 M")
        self.mapping_client = Mock()
        self.mapping_client.list_spu_sku_mappings.return_value = [self.mapping]

    @patch("jd_competitor_analysis.warehouse_daily.normalize_daily_dataset")
    @patch("jd_competitor_analysis.warehouse_daily.read_self_sku_daily")
    @patch("jd_competitor_analysis.warehouse_daily.read_competitor_sources")
    def test_build_daily_dataset_reuses_normalization_entry(
        self,
        read_sources: Mock,
        read_self: Mock,
        normalize_dataset: Mock,
    ) -> None:
        """正式入口应读取全部来源并调用统一的完整数据组装函数。"""

        raw_sources = {
            "core_metrics": [{"product_role": "self", "value": None}],
            "traffic_sources": [],
            "traffic_keywords": [],
            "customer_profiles": [],
            "promotion": [],
        }
        sku_rows = [{"sku_id": "30001"}]
        read_sources.return_value = raw_sources
        read_self.return_value = sku_rows
        normalize_dataset.return_value = {"quality": {"status": "partial"}}

        result = build_daily_dataset(
            Mock(),
            self.pair,
            "2026-08-11",
            self.mapping_client,
        )

        self.assertEqual(result["quality"]["status"], "partial")
        self.mapping_client.list_spu_sku_mappings.assert_called_once_with("10001")
        read_self.assert_called_once()
        self.assertEqual(read_self.call_args.args[2], ["30001"])
        normalize_dataset.assert_called_once_with(
            raw_sources,
            self.pair,
            "2026-08-11",
            [self.mapping],
            sku_rows,
        )

    @patch("jd_competitor_analysis.warehouse_daily.read_competitor_sources")
    def test_all_sources_empty_stops_before_lark_and_self_queries(
        self,
        read_sources: Mock,
    ) -> None:
        """五张来源表全部为空时应跳过商品对且不读取本品数据。"""

        read_sources.return_value = {
            "core_metrics": [],
            "traffic_sources": [],
            "traffic_keywords": [],
            "customer_profiles": [],
            "promotion": [],
        }

        with self.assertRaises(WarehousePairNoDataError):
            build_daily_dataset(Mock(), self.pair, "2026-08-11", self.mapping_client)

        self.mapping_client.list_spu_sku_mappings.assert_not_called()

    def test_any_source_row_is_available_regardless_of_role_or_value(self) -> None:
        """任意来源记录都应视为商品对有数据，不检查角色和值。"""

        raw_sources = {
            "core_metrics": [],
            "traffic_sources": [{"product_role": "self", "value": None}],
            "traffic_keywords": [],
            "customer_profiles": [],
            "promotion": [],
        }

        self.assertEqual(count_competitor_source_rows(raw_sources), 1)


if __name__ == "__main__":
    unittest.main()
