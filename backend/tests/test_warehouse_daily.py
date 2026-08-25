"""测试完整标准化日数据的可复用构建入口。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from jd_competitor_analysis.lark_mapping import SkuMapping
from jd_competitor_analysis.warehouse_daily import (
    WarehouseDataIncompleteError,
    build_daily_dataset,
    find_missing_source_roles,
)
from jd_competitor_analysis.warehouse_sources import ProductPair


class WarehouseDailyDatasetTest(unittest.TestCase):
    """验证外部来源读取顺序和五表记录门槛。"""

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
            source_id: [
                {"product_role": "self", "value": None},
                {"product_role": "competitor", "value": "masked"},
            ]
            for source_id in (
                "core_metrics",
                "traffic_sources",
                "traffic_keywords",
                "customer_profiles",
                "promotion",
            )
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
    def test_missing_source_role_stops_before_lark_and_self_queries(
        self,
        read_sources: Mock,
    ) -> None:
        """任一来源缺少本品或竞品记录时应保留报告缺口。"""

        read_sources.return_value = {
            "core_metrics": [
                {"product_role": "self"},
                {"product_role": "competitor"},
            ],
            "traffic_sources": [{"product_role": "self"}],
            "traffic_keywords": [
                {"product_role": "self"},
                {"product_role": "competitor"},
            ],
            "customer_profiles": [
                {"product_role": "self"},
                {"product_role": "competitor"},
            ],
            "promotion": [
                {"product_role": "self"},
                {"product_role": "competitor"},
            ],
        }

        with self.assertRaises(WarehouseDataIncompleteError) as captured:
            build_daily_dataset(Mock(), self.pair, "2026-08-11", self.mapping_client)

        self.assertEqual(
            captured.exception.missing_roles,
            {"traffic_sources": ["competitor"]},
        )
        self.mapping_client.list_spu_sku_mappings.assert_not_called()

    def test_internal_values_do_not_affect_source_completeness(self) -> None:
        """记录内部为空、脱敏或零值时仍视为表级记录完整。"""

        raw_sources = {
            source_id: [
                {"product_role": "self", "value": None},
                {"product_role": "competitor", "value": value},
            ]
            for source_id, value in (
                ("core_metrics", "masked"),
                ("traffic_sources", 0),
                ("traffic_keywords", None),
                ("customer_profiles", "masked"),
                ("promotion", 0),
            )
        }

        self.assertEqual(find_missing_source_roles(raw_sources), {})


if __name__ == "__main__":
    unittest.main()
