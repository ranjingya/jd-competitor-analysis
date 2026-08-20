"""测试数仓标准化日数据的确定性分析适配。"""

from __future__ import annotations

import unittest
from typing import Any

from jd_competitor_analysis.warehouse_analysis import (
    adapt_daily_dataset,
    analyze_daily_dataset,
    build_ai_task_payload,
)


def metric(value: int | float, unit: str = "count") -> dict[str, Any]:
    """生成精确值指标对象。"""

    raw = f"{value * 100}%" if unit == "ratio" else str(value)
    return {"raw": raw, "status": "exact", "low": value, "high": value, "unit": unit}


def masked_metric(unit: str = "ratio") -> dict[str, Any]:
    """生成数仓未披露指标对象。"""

    return {"raw": "-", "status": "masked", "low": None, "high": None, "unit": unit}


def source(records: list[dict[str, Any]], status: str = "ready") -> dict[str, Any]:
    """生成固定来源外层。"""

    return {
        "source": {"table": "test_table", "updated_at": None, "row_ids": [], "row_count": len(records)},
        "records": records,
        "quality": {"status": status, "issues": []},
    }


def daily_dataset() -> dict[str, Any]:
    """生成可完成固定公式分析的日数据。"""

    self_metrics = {
        "page_views": 100,
        "visitors": 50,
        "buyers": 10,
        "orders": 8,
        "units_sold": 10,
        "gmv": 1000,
        "add_to_cart_users": 10,
        "conversion_rate": 0.2,
        "average_order_value": 100,
        "search_clicks": 20,
    }
    self_core = {
        "page_views": metric(100),
        "visitors": metric(50),
        "add_to_cart_users": metric(10),
        "orders": metric(8),
        "units_sold": metric(10),
        "gmv": metric(1000, "currency"),
        "conversion_rate": metric(0.2, "ratio"),
        "average_order_value": metric(100, "currency"),
        "search_clicks": metric(20),
    }
    competitor_core = {
        "page_views": metric(120),
        "visitors": metric(60),
        "add_to_cart_users": metric(12),
        "orders": metric(10),
        "units_sold": metric(12),
        "gmv": metric(1200, "currency"),
        "conversion_rate": metric(0.2, "ratio"),
        "average_order_value": metric(100, "currency"),
        "search_clicks": metric(25),
    }
    return {
        "schema_version": "2.0",
        "report_date": "2026-08-18",
        "pair": {
            "compare_number": "10001+20001",
            "self_spu": "10001",
            "competitor_spu": "20001",
        },
        "self_product": {
            "spu_id": "10001",
            "sku_components": [
                {
                    "spu_id": "10001",
                    "sku_id": "30001",
                    "barcode_69": "69001",
                    "product_name": "测试商品",
                    "specification": "测试规格",
                }
            ],
            "sku_daily_records": [],
            "spu_daily_metrics": self_metrics,
            "quality": {"status": "ready", "issues": []},
        },
        "sources": {
            "core_metrics": source([{"self": self_core, "competitor": competitor_core}]),
            "traffic_sources": source([], "unavailable"),
            "traffic_keywords": source([], "unavailable"),
            "customer_profiles": source([], "unavailable"),
            "promotion": source([], "unavailable"),
        },
        "quality": {"status": "partial", "issues": []},
    }


class WarehouseAnalysisTest(unittest.TestCase):
    """验证结构适配、固定公式和 AI 任务事实。"""

    def test_daily_dataset_runs_existing_deterministic_analysis(self) -> None:
        """本品真实值和竞品区间应进入现有 P 值与约束公式。"""

        dataset = daily_dataset()
        normalized = adapt_daily_dataset(dataset)
        report = analyze_daily_dataset(dataset, product_images={})

        self.assertEqual(normalized["self_real"]["成交金额"], 1000)
        self.assertEqual(normalized["core_raw"]["竞品1成交金额"], "1200")
        gmv = next(item for item in report["comparison"] if item["metric_id"] == "gmv")
        self.assertEqual(gmv["self_value"], 1000)
        self.assertEqual(gmv["competitor_value"], 1200)
        self.assertEqual(report["ai_recommendations"], [])
        self.assertIn("缺少关键词数据，关键词 Tab 不完整", report["risks"])
        self.assertIn("缺少客户画像数据，客户画像 Tab 不完整", report["risks"])

    def test_ai_payload_contains_only_self_spu_and_five_tables(self) -> None:
        """AI 输入只应包含基础标识、本品 SPU 汇总值和五张表。"""

        dataset = daily_dataset()
        report = analyze_daily_dataset(dataset, product_images={})
        report["meta"]["generated_at"] = "2026-08-19T10:00:00"
        first = build_ai_task_payload(dataset, report)
        report["meta"]["generated_at"] = "2026-08-19T11:00:00"
        second = build_ai_task_payload(dataset, report)

        self.assertEqual(first, second)
        self.assertEqual(set(first), {"period", "pair", "self_spu_data", "tables"})
        self.assertEqual(
            first["period"],
            {"granularity": "day", "start_date": "2026-08-18", "end_date": "2026-08-18"},
        )
        self.assertEqual(first["self_spu_data"]["spu_id"], "10001")
        self.assertEqual(first["self_spu_data"]["metrics"], dataset["self_product"]["spu_daily_metrics"])
        self.assertEqual(
            set(first["tables"]),
            {"core_metrics", "traffic_sources", "traffic_keywords", "customer_profiles", "promotion"},
        )

    def test_ai_payload_keeps_all_business_rows_and_removes_display_fields(self) -> None:
        """AI 输入应保留全部业务行，并排除图片和页面重复结构。"""

        dataset = daily_dataset()
        report = analyze_daily_dataset(dataset, product_images={})
        report["meta"]["self_product"] = {"id": "10001", "image_url": "https://example.test/a.jpg"}
        report["tabs"] = [{"rows": [{"duplicated": True}]}]
        report["keywords"] = {
            "summary": {},
            "coverage": {},
            "rows": [
                {
                    "keyword": f"关键词{index}",
                    "coverage_relation": f"关系{index % 3}",
                    "self_visitors": index,
                    "competitor_visitors": index + 1,
                    "self_gmv": index * 10,
                    "competitor_gmv": index * 20,
                }
                for index in range(120)
            ],
            "notes": [],
        }
        report["customer_profile"] = {
            "dimensions": [
                {
                    "dimension": "测试维度",
                    "items": [
                        {"name": f"画像{index}", "self_rate": index, "competitor_rate": index + 1}
                        for index in range(80)
                    ],
                }
            ],
            "notes": [],
        }

        payload = build_ai_task_payload(dataset, report)
        tables = payload["tables"]

        self.assertEqual(len(tables["traffic_keywords"]["rows"]), 120)
        self.assertEqual(len(tables["customer_profiles"]["dimensions"][0]["items"]), 80)
        self.assertNotIn("tabs", str(payload))
        self.assertNotIn("image_url", str(payload))
        self.assertNotIn("barcode_69", str(payload))
        self.assertNotIn("sku_id", str(payload))

    def test_partial_profile_keeps_single_side_rows_without_missing_risk(self) -> None:
        """画像单侧未披露时应保留事实，且不能误判为整块画像缺失。"""

        dataset = daily_dataset()
        dataset["sources"]["customer_profiles"] = source(
            [
                {
                    "dimension": "age",
                    "segment": "16–25岁",
                    "self_share": masked_metric(),
                    "competitor_share": metric(0.0159, "ratio"),
                },
                {
                    "dimension": "age",
                    "segment": "56岁以上",
                    "self_share": metric(0.0149, "ratio"),
                    "competitor_share": masked_metric(),
                },
            ],
            "partial",
        )

        normalized = adapt_daily_dataset(dataset)
        report = analyze_daily_dataset(dataset, product_images={})
        profile_items = report["customer_profile"]["dimensions"][0]["items"]

        self.assertEqual(
            next(
                item
                for item in normalized["source_files"]
                if item["role"] == "customer_profile"
            )["status"],
            "ready",
        )
        self.assertIsNone(profile_items[0]["self_rate"])
        self.assertEqual(profile_items[0]["competitor_rate"], 1.59)
        self.assertIsNone(profile_items[0]["gap_rate"])
        self.assertEqual(profile_items[1]["self_rate"], 1.49)
        self.assertIsNone(profile_items[1]["competitor_rate"])
        self.assertIsNone(profile_items[1]["gap_rate"])
        self.assertNotIn("缺少客户画像数据，客户画像 Tab 不完整", report["risks"])

    def test_partial_keywords_do_not_trigger_missing_tab_risk(self) -> None:
        """关键词含未披露指标时仍应视为已读取来源。"""

        dataset = daily_dataset()
        dataset["sources"]["traffic_keywords"] = source(
            [
                {
                    "spu_id": "10001",
                    "product_name": "测试商品",
                    "keyword": "儿童雨衣",
                    "visitors": metric(10),
                    "gmv": masked_metric("currency"),
                }
            ],
            "partial",
        )

        report = analyze_daily_dataset(dataset, product_images={})

        self.assertEqual(report["keywords"]["summary"]["self_only_count"], 1)
        self.assertNotIn("缺少关键词数据，关键词 Tab 不完整", report["risks"])

    def test_invalid_dataset_is_rejected(self) -> None:
        """核心事实无效时不得生成正式报告。"""

        dataset = daily_dataset()
        dataset["quality"]["status"] = "invalid"

        with self.assertRaisesRegex(ValueError, "invalid"):
            adapt_daily_dataset(dataset)


if __name__ == "__main__":
    unittest.main()
