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

    def test_ai_payload_excludes_volatile_generated_time(self) -> None:
        """AI 输入不应因报告生成时间变化而产生新版本。"""

        dataset = daily_dataset()
        report = analyze_daily_dataset(dataset, product_images={})
        report["meta"]["generated_at"] = "2026-08-19T10:00:00"
        first = build_ai_task_payload("dataset-1", dataset, report)
        report["meta"]["generated_at"] = "2026-08-19T11:00:00"
        second = build_ai_task_payload("dataset-1", dataset, report)

        self.assertEqual(first, second)
        self.assertNotIn("generated_at", first["deterministic_report"]["meta"])

    def test_invalid_dataset_is_rejected(self) -> None:
        """核心事实无效时不得生成正式报告。"""

        dataset = daily_dataset()
        dataset["quality"]["status"] = "invalid"

        with self.assertRaisesRegex(ValueError, "invalid"):
            adapt_daily_dataset(dataset)


if __name__ == "__main__":
    unittest.main()
