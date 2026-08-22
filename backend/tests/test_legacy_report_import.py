"""测试历史 Excel 报告结构适配与导入。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.jobs.legacy_report_import import adapt_legacy_report, import_legacy_reports
from app.repositories.report_repository import ReportRepository
from jd_competitor_analysis.contracts import empty_contract


def _legacy_report() -> dict:
    """生成包含旧差距字段的最小历史报告。"""

    report = empty_contract()
    report.pop("ai_findings")
    report["meta"].update(
        {
            "title": "历史报告",
            "period": "2026-06-01",
            "period_start": "2026-06-01",
            "period_end": "2026-06-01",
            "period_key": "day:2026-06-01_2026-06-01",
            "granularity": "day",
            "self_spu": "10001",
            "competitor_spu": "20001",
            "self_product": {
                "id": "10001",
                "name": "本品",
                "image_url": "https://example.com/self.jpg",
            },
            "competitor_product": {
                "id": "20001",
                "name": "竞品",
                "image_url": "https://example.com/competitor.jpg",
            },
            "confidence": "medium",
        }
    )
    report["core_metrics"] = [
        {
            "id": metric_id,
            "label": label,
            "unit": unit,
            "self_value": self_value,
            "competitor_value": competitor_value,
            "gap_abs_text": "旧差值",
            "ratio_text": "旧倍数",
            "gap_text": "旧展示文本",
            "status": "advantage",
            "priority": "低",
        }
        for metric_id, label, unit, self_value, competitor_value in (
            ("gmv", "成交金额", "", 300.0, 200.0),
            ("visitors", "访客数", "", 150.0, 200.0),
            ("conversion_rate", "成交转化率", "%", 15.0, 20.0),
            ("customer_price", "成交客单价", "", 50.0, 100.0),
        )
    ]
    report["comparison"] = [
        {
            "metric_id": "gmv",
            "self_value": 300.0,
            "competitor_value": 200.0,
            "ratio": 1.5,
        }
    ]
    for tab in report["tabs"]:
        tab["highlights"] = [
            {
                "label": "旧重点项",
                "self_value": 30.0,
                "competitor_value": 20.0,
                "unit": "%" if tab["id"] == "customer_profile" else "",
                "gap_text": "旧重点文本",
                "status": "advantage",
            }
        ]
    return report


class LegacyReportImportTest(unittest.TestCase):
    """验证历史报告只补结构字段并作为独立报告入库。"""

    def test_adapter_preserves_legacy_content_and_adds_current_fields(self) -> None:
        """适配器应保留旧文本和元数据，同时补齐当前差距结构。"""

        adapted = adapt_legacy_report(_legacy_report())
        cards = {item["id"]: item for item in adapted["core_metrics"]}

        self.assertEqual(adapted["ai_findings"], [])
        self.assertNotIn("confidence", adapted["meta"])
        self.assertEqual(cards["gmv"]["gap_text"], "旧展示文本")
        self.assertEqual(cards["gmv"]["gap_abs_text"], "旧差值")
        self.assertEqual(cards["gmv"]["gap_value"], 100.0)
        self.assertEqual(cards["gmv"]["gap_rate_pct"], 50.0)
        self.assertEqual(cards["conversion_rate"]["gap_value"], -5.0)
        self.assertIsNone(cards["conversion_rate"]["gap_rate_pct"])
        self.assertEqual(cards["conversion_rate"]["gap_mode"], "percentage_point")
        self.assertEqual(adapted["tabs"][0]["highlights"][0]["metric_label"], "访客")

    def test_import_is_repeatable_and_day_report_has_no_dataset(self) -> None:
        """独立 SPU 日报重复导入时应更新同一业务报告且不创建数据集。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source" / "day" / "2026-06-01" / "analysis_result.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(_legacy_report(), ensure_ascii=False),
                encoding="utf-8",
            )
            repository = ReportRepository(root / "data.db")
            repository.initialize()

            first = import_legacy_reports(root / "source", repository)
            second = import_legacy_reports(root / "source", repository)
            records = repository.read_index()["reports"]["day"]

            self.assertEqual(first["count"], 1)
            self.assertEqual(second["count"], 1)
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0]["dataset_id"])
            self.assertEqual(records[0]["status"], "ready")
            self.assertEqual(repository.get_skus(records[0]["report_id"])["items"], [])


if __name__ == "__main__":
    unittest.main()
