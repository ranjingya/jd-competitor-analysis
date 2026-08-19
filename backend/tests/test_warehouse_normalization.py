"""测试五张数仓竞品表的标准化结构。"""

from __future__ import annotations

import unittest

from jd_competitor_analysis.warehouse_normalization import (
    normalize_competitor_sources,
    normalize_core_metrics,
    normalize_customer_profiles,
    normalize_metric,
    normalize_promotion,
    normalize_traffic_keywords,
    normalize_traffic_sources,
)
from jd_competitor_analysis.warehouse_sources import ProductPair


PAIR = ProductPair.parse("100174558585+100112260075")


def source_row(row_id: int, data: dict[str, object]) -> dict[str, object]:
    """生成标准数仓来源测试行。"""

    return {
        "id": row_id,
        "dt": "2026-08-11",
        "compare_number": PAIR.compare_number,
        "self_spu": PAIR.self_spu,
        "competitor_spu": PAIR.competitor_spu,
        "updated_at": "2026-08-12 03:00:00",
        "data": data,
    }


class MetricNormalizationTest(unittest.TestCase):
    """验证公共指标值解析。"""

    def test_range_exact_and_ratio_values(self) -> None:
        """货币区间、单值和百分比应输出统一上下界。"""

        self.assertEqual(
            normalize_metric("￥1,000 ~ ￥2,000", "currency"),
            {"raw": "￥1,000 ~ ￥2,000", "status": "range", "low": 1000, "high": 2000, "unit": "currency"},
        )
        self.assertEqual(
            normalize_metric("0", "count"),
            {"raw": "0", "status": "exact", "low": 0, "high": 0, "unit": "count"},
        )
        self.assertEqual(
            normalize_metric("7.5% ~ 10%", "ratio"),
            {"raw": "7.5% ~ 10%", "status": "range", "low": 0.075, "high": 0.1, "unit": "ratio"},
        )

    def test_missing_fields_and_dash_are_both_masked(self) -> None:
        """固定字段不存在和源值为横线时都应标记为 masked。"""

        self.assertEqual(normalize_metric(None, "count")["status"], "masked")
        self.assertIsNone(normalize_metric(None, "count")["raw"])
        self.assertEqual(normalize_metric("-", "count")["status"], "masked")
        self.assertEqual(normalize_metric("-", "count")["raw"], "-")

    def test_invalid_value_does_not_become_masked(self) -> None:
        """存在但无法解析的值应保留 invalid 状态。"""

        result = normalize_metric("未知", "currency")

        self.assertEqual(result["status"], "invalid")
        self.assertIsNone(result["low"])
        self.assertIsNone(result["high"])


class SourceNormalizationTest(unittest.TestCase):
    """验证五类来源的字段、角色和质量状态。"""

    def test_core_metrics_have_fixed_fields(self) -> None:
        """核心指标两侧都应包含完整固定字段。"""

        result = normalize_core_metrics(
            [
                source_row(
                    1,
                    {
                        "本品浏览量": "50 ~ 100",
                        "本品访客数": "10 ~ 50",
                        "竞品1浏览量": "400 ~ 600",
                        "竞品1访客数": "200 ~ 400",
                        "竞品1成交金额": "￥1,000 ~ ￥2,000",
                    },
                )
            ]
        )

        expected_fields = {
            "page_views",
            "visitors",
            "add_to_cart_users",
            "orders",
            "units_sold",
            "gmv",
            "conversion_rate",
            "average_order_value",
            "search_clicks",
        }
        self.assertEqual(set(result["records"][0]["self"]), expected_fields)
        self.assertEqual(set(result["records"][0]["competitor"]), expected_fields)
        self.assertEqual(result["records"][0]["self"]["gmv"]["status"], "masked")
        self.assertEqual(result["quality"]["status"], "partial")

    def test_traffic_sources_keep_channel_path_and_fixed_metrics(self) -> None:
        """流量来源应清理空层级并固定两侧指标字段。"""

        result = normalize_traffic_sources(
            [
                source_row(
                    2,
                    {
                        "一级渠道": "站内场域",
                        "二级渠道": "搜索",
                        "三级渠道": "-",
                        "本品访客数": "400 ~ 600",
                        "本品访客数占比": "70% ~ 75%",
                        "竞品1访客数": "200 ~ 400",
                        "竞品1成交转化率": "10% ~ 15%",
                    },
                )
            ]
        )

        record = result["records"][0]
        self.assertEqual(record["channel_path"], "站内场域 > 搜索")
        self.assertIsNone(record["channel_level_3"])
        self.assertEqual(
            set(record["self"]),
            {"visitors", "visitor_share", "gmv", "conversion_rate", "buyers"},
        )
        self.assertEqual(record["self"]["visitor_share"]["low"], 0.7)

    def test_keywords_identify_both_product_roles(self) -> None:
        """关键词记录应按 SPU 标记本品或竞品。"""

        result = normalize_traffic_keywords(
            [
                source_row(
                    3,
                    {
                        "SPUID": PAIR.self_spu,
                        "关键词": "雨衣",
                        "商品名称": "本品雨衣",
                        "访客数": "10 ~ 50",
                        "成交金额": "￥200 ~ ￥400",
                    },
                ),
                source_row(
                    4,
                    {
                        "SPUID": PAIR.competitor_spu,
                        "关键词": "儿童雨衣",
                        "商品名称": "竞品雨衣",
                        "访客数": "50 ~ 100",
                        "成交金额": "￥400 ~ ￥600",
                    },
                ),
            ],
            PAIR,
        )

        self.assertEqual([item["product_role"] for item in result["records"]], ["self", "competitor"])
        self.assertEqual(result["quality"]["status"], "ready")

    def test_profile_uses_heading_order_and_fills_missing_share(self) -> None:
        """画像标题应作用于后续项，缺少占比字段时固定补 masked。"""

        result = normalize_customer_profiles(
            [
                source_row(10, {"画像类型": "年龄"}),
                source_row(
                    11,
                    {
                        "画像类型": "16-25岁",
                        "本品成交客户数占比": "1.32%",
                    },
                ),
            ]
        )

        self.assertEqual(len(result["records"]), 1)
        record = result["records"][0]
        self.assertEqual(record["dimension"], "age")
        self.assertEqual(record["segment"], "16-25岁")
        self.assertEqual(record["self_share"]["low"], 0.0132)
        self.assertEqual(record["competitor_share"]["status"], "masked")
        self.assertEqual(result["quality"]["status"], "partial")

    def test_profile_without_heading_can_infer_age(self) -> None:
        """批次缺少标题行时可从明确的年龄项推断维度。"""

        result = normalize_customer_profiles(
            [source_row(12, {"画像类型": "16-25岁", "本品成交客户数占比": "1.32%"})]
        )

        self.assertEqual(result["records"][0]["dimension"], "age")

    def test_promotion_contains_full_and_non_full_site_fields(self) -> None:
        """推广记录应同时保留全站和非全站固定指标。"""

        result = normalize_promotion(
            [
                source_row(
                    20,
                    {
                        "非全站-本店商品广告点击数": "0",
                        "非全站-本店商品广告总订单金额": "0",
                        "非全站-竞品1广告点击数": "200 ~ 400",
                        "非全站-竞品1广告总订单金额": "￥800 ~ ￥1,000",
                    },
                )
            ]
        )

        record = result["records"][0]
        self.assertEqual(record["self"]["non_full_site"]["ad_clicks"]["status"], "exact")
        self.assertEqual(record["competitor"]["non_full_site"]["ad_order_gmv"]["high"], 1000)
        self.assertEqual(record["self"]["full_site"]["gmv"]["status"], "masked")

    def test_all_sources_have_common_wrapper(self) -> None:
        """总转换结果应始终包含五个来源及统一外层。"""

        raw_sources = {
            "core_metrics": [source_row(1, {"本品访客数": "10 ~ 50", "竞品1访客数": "50 ~ 100"})],
            "traffic_sources": [],
            "traffic_keywords": [],
            "customer_profiles": [],
            "promotion": [],
        }

        result = normalize_competitor_sources(raw_sources, PAIR, "2026-08-11")

        self.assertEqual(result["schema_version"], "2.0")
        self.assertEqual(result["pair"]["compare_number"], PAIR.compare_number)
        self.assertEqual(
            set(result["sources"]),
            {"core_metrics", "traffic_sources", "traffic_keywords", "customer_profiles", "promotion"},
        )
        for source in result["sources"].values():
            self.assertEqual(set(source), {"source", "records", "quality"})
        self.assertEqual(result["quality"]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
