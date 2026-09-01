"""测试日报聚合生成周报和月报。"""

from __future__ import annotations

import unittest
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from app.database import Database
from app.jobs.period_analysis import (
    _run_period_pair,
    month_range,
    previous_month,
    previous_week,
    week_from_start,
)
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskRepository
from jd_competitor_analysis.contracts import empty_contract
from jd_competitor_analysis.period_aggregation import (
    aggregate_period_report,
    build_period_ai_payload,
)


def daily_row(report_date: str, gmv: float, visitors: float, buyers: float) -> dict[str, object]:
    """生成一条周期聚合使用的最小完整日报。"""

    report = empty_contract()
    report["meta"].update(
        {
            "title": "测试报告",
            "period": report_date,
            "period_start": report_date,
            "period_end": report_date,
            "period_key": f"day:{report_date}",
            "granularity": "day",
            "self_spu": "10001",
            "competitor_spu": "20001",
            "self_name": "本品",
            "competitor_name": "竞品",
            "self_product": {"id": "10001", "name": "本品", "image_url": None},
            "competitor_product": {"id": "20001", "name": "竞品", "image_url": None},
        }
    )
    competitor_gmv = gmv / 2
    competitor_visitors = visitors / 2
    competitor_buyers = buyers / 2
    values = {
        "gmv": (gmv, competitor_gmv),
        "sold_units": (buyers * 2, competitor_buyers * 2),
        "orders": (buyers, competitor_buyers),
        "views": (visitors * 3, competitor_visitors * 3),
        "visitors": (visitors, competitor_visitors),
        "cart_users": (buyers * 3, competitor_buyers * 3),
        "conversion_rate": (buyers / visitors, competitor_buyers / competitor_visitors),
        "customer_price": (gmv / buyers, competitor_gmv / competitor_buyers),
    }
    report["comparison"] = [
        {
            "metric_id": metric_id,
            "metric_label": metric_id,
            "self_value": self_value,
            "competitor_value": competitor_value,
        }
        for metric_id, (self_value, competitor_value) in values.items()
    ]
    return {
        "report_id": f"report-{report_date}",
        "report_date": report_date,
        "self_spu": "10001",
        "competitor_spu": "20001",
        "self_buyers": buyers,
        "competitor_buyers": competitor_buyers,
        "report": report,
    }


class PeriodAggregationTest(unittest.TestCase):
    """验证周期日期、核心公式和 AI 输入边界。"""

    def test_week_uses_calendar_days_and_records_missing_dates(self) -> None:
        """缺少日报时仍应按自然周七天计算日均值。"""

        report = aggregate_period_report(
            [
                daily_row("2026-08-10", 700, 100, 10),
                daily_row("2026-08-12", 1400, 200, 20),
            ],
            "week",
            "2026-08-10",
            "2026-08-16",
        )
        comparison = {item["metric_id"]: item for item in report["comparison"]}

        self.assertEqual(comparison["gmv"]["self_value"], 2100)
        self.assertEqual(comparison["conversion_rate"]["self_value"], 0.1)
        self.assertEqual(comparison["customer_price"]["self_value"], 70)
        self.assertEqual(report["meta"]["period_days"], 7)
        self.assertEqual(report["meta"]["available_days"], 2)
        self.assertEqual(len(report["meta"]["missing_days"]), 5)
        self.assertEqual(report["meta"]["daily_averages"]["gmv"]["self_value"], 300)
        self.assertEqual(report["quality_status"], "partial")

    def test_period_ai_payload_excludes_tabs_and_daily_ai_text(self) -> None:
        """周期 AI 输入只应包含聚合业务事实。"""

        report = aggregate_period_report(
            [daily_row("2026-08-10", 700, 100, 10)],
            "week",
            "2026-08-10",
            "2026-08-16",
        )
        payload = build_period_ai_payload(report)

        self.assertEqual(payload["period"]["period_days"], 7)
        self.assertEqual(
            set(payload["tables"]),
            {
                "core_metrics",
                "traffic_sources",
                "traffic_keywords",
                "customer_profiles",
                "promotion",
            },
        )
        self.assertNotIn("tabs", payload)
        self.assertNotIn("ai_findings", payload)

    def test_natural_period_helpers_handle_leap_year(self) -> None:
        """自然周和闰年二月范围应准确。"""

        self.assertEqual(previous_week(date(2026, 8, 26)), ("2026-08-17", "2026-08-23"))
        self.assertEqual(week_from_start("2026-08-17"), ("2026-08-17", "2026-08-23"))
        self.assertEqual(previous_month(date(2026, 3, 1)), ("2026-02-01", "2026-02-28"))
        self.assertEqual(month_range("2024-02"), ("2024-02-01", "2024-02-29"))
        with self.assertRaisesRegex(ValueError, "周一"):
            week_from_start("2026-08-18")

    def test_period_report_is_persisted_once_for_same_daily_sources(self) -> None:
        """相同来源日报应复用唯一周期报告且不重复调用模型。"""

        analyzer = Mock()
        analyzer.model = "deepseek-v4-pro"
        analyzer.analysis_version = "1.0"
        analyzer.prompt_hash = "prompt-hash"
        analyzer.analyze.return_value = {
            "summary": {
                "advantage": {"brief": "成交金额领先", "detail": ["周期成交金额领先。"]},
                "weakness": {"brief": "暂无明显短板", "detail": ["当前数据未显示明显短板。"]},
            },
            "findings": [],
            "recommendations": [],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Database(Path(temporary_directory) / "data.db")
            database.initialize()
            reports = ReportRepository(database)
            tasks = TaskRepository(database)
            source = daily_row("2026-08-10", 700, 100, 10)
            source_report_id = reports.upsert(None, source["report"], status="ready")
            rows = reports.list_ready_day_reports(
                "2026-08-10", "2026-08-16", "10001", "20001"
            )

            first = _run_period_pair(
                rows, "week", "2026-08-10", "2026-08-16", reports, tasks, analyzer
            )
            second = _run_period_pair(
                rows, "week", "2026-08-10", "2026-08-16", reports, tasks, analyzer
            )
            stored = reports.get_record(first["report_id"])

        self.assertEqual(first["status"], "ready")
        self.assertEqual(second["status"], "existing")
        self.assertEqual(first["report_id"], second["report_id"])
        self.assertIsNone(stored["dataset_id"])
        self.assertEqual(stored["report"]["meta"]["source_report_ids"], [source_report_id])
        analyzer.analyze.assert_called_once()


if __name__ == "__main__":
    unittest.main()
