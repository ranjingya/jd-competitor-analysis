"""测试完整标准化日数据的可复用构建入口。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from jd_competitor_analysis.lark_mapping import SkuMapping
from jd_competitor_analysis.warehouse_daily import build_daily_dataset
from jd_competitor_analysis.warehouse_sources import ProductPair


class WarehouseDailyDatasetTest(unittest.TestCase):
    """验证外部来源读取顺序和核心数据门槛。"""

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
            "core_metrics": [{"id": 1}],
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
    def test_missing_core_source_stops_before_lark_and_self_queries(self, read_sources: Mock) -> None:
        """核心表没有商品对时应直接跳过后续映射和本品查询。"""

        read_sources.return_value = {
            "core_metrics": [],
            "traffic_sources": [],
            "traffic_keywords": [],
            "customer_profiles": [],
            "promotion": [],
        }

        with self.assertRaisesRegex(LookupError, "核心指标表没有商品对日数据"):
            build_daily_dataset(Mock(), self.pair, "2026-08-11", self.mapping_client)

        self.mapping_client.list_spu_sku_mappings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
