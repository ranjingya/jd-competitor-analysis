"""提供基于当前数据库报告契约的测试对象。"""

from __future__ import annotations

from typing import Any

from jd_competitor_analysis.contracts import empty_contract


def build_report_fixture(report_date: str = "2026-08-17") -> dict[str, Any]:
    """生成一份可通过当前报告契约校验的日分析结果。"""

    report = empty_contract()
    report["meta"].update(
        {
            "title": "竞品分析测试报告",
            "period": report_date,
            "period_start": report_date,
            "period_end": report_date,
            "period_key": f"day:{report_date}",
            "granularity": "day",
            "self_name": "本品测试商品",
            "self_spu": "10001",
            "self_product": {
                "id": "10001",
                "name": "本品测试商品",
                "image_url": "https://example.com/self.jpg",
            },
            "competitor_name": "竞品测试商品",
            "competitor_spu": "20001",
            "competitor_product": {
                "id": "20001",
                "name": "竞品测试商品",
                "image_url": "https://example.com/competitor.jpg",
            },
            "summary": "本品成交金额领先",
            "weakness_summary": "本品成交转化率落后",
            "generated_at": f"{report_date}T12:00:00",
        }
    )
    report["core_metrics"] = [
        {
            "id": "gmv",
            "label": "成交金额",
            "unit": "",
            "self_value": 1200.0,
            "competitor_value": 1000.0,
            "gap_value": 200.0,
            "gap_rate_pct": 20.0,
            "gap_mode": "relative",
            "gap_text": "领先 20.00%",
            "status": "advantage",
        },
        {
            "id": "visitors",
            "label": "访客数",
            "unit": "",
            "self_value": 200.0,
            "competitor_value": 180.0,
            "gap_value": 20.0,
            "gap_rate_pct": 11.11,
            "gap_mode": "relative",
            "gap_text": "领先 11.11%",
            "status": "advantage",
        },
        {
            "id": "conversion_rate",
            "label": "成交转化率",
            "unit": "%",
            "self_value": 8.0,
            "competitor_value": 10.0,
            "gap_value": -2.0,
            "gap_rate_pct": None,
            "gap_mode": "percentage_point",
            "gap_text": "落后 2.00pct",
            "status": "warning",
        },
        {
            "id": "customer_price",
            "label": "成交客单价",
            "unit": "",
            "self_value": 75.0,
            "competitor_value": 55.56,
            "gap_value": 19.44,
            "gap_rate_pct": 34.99,
            "gap_mode": "relative",
            "gap_text": "领先 34.99%",
            "status": "advantage",
        },
    ]
    return report
