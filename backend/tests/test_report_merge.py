"""测试 AI 生成内容与基础报告合并。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.report_merge import merge_ai_result, validate_ai_result


ASSET_PATH = Path(__file__).resolve().parents[1] / "assets" / "analysis-result.example.json"


def base_report() -> dict[str, object]:
    """读取通过最终契约校验的基础报告。"""

    report = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
    report["ai_recommendations"] = []
    return report


def recommendation(source_id: str, source_label: str) -> dict[str, object]:
    """生成一条结构完整的 AI 建议。"""

    return {
        "source_id": source_id,
        "source_label": source_label,
        "target": "测试对象",
        "status": "warning",
        "evidence": "本品指标低于竞品估算值",
        "actions": ["调整对应运营动作"],
        "validation": "后续日数据差距缩小",
    }


class ReportMergeTest(unittest.TestCase):
    """验证 AI 字段边界、报告投影和最终契约。"""

    def test_ai_result_is_merged_without_losing_deterministic_summary(self) -> None:
        """AI 总结应成为看板摘要，同时保留固定公式摘要用于审计。"""

        report = base_report()
        deterministic_summary = report["meta"]["summary"]
        result = {
            "summary": "流量领先，但转化效率仍是主要短板。",
            "findings": [
                {
                    "source_id": "traffic",
                    "target": "搜索渠道",
                    "judgement": "流量规模领先但转化偏低",
                    "evidence": "访客领先，成交转化率落后",
                }
            ],
            "recommendations": [
                recommendation("traffic", "流量来源"),
                recommendation("promotion", "推广数据"),
            ],
        }

        merged = merge_ai_result(report, result)

        self.assertEqual(merged["meta"]["summary"], result["summary"])
        self.assertEqual(merged["meta"]["deterministic_summary"], deterministic_summary)
        self.assertEqual(merged["ai_findings"], result["findings"])
        self.assertEqual(merged["ai_recommendations"], result["recommendations"])
        self.assertEqual(report["ai_findings"], [])

    def test_empty_recommendations_are_allowed_when_evidence_is_insufficient(self) -> None:
        """证据不足时可以完成分析但不生成建议。"""

        validated = validate_ai_result(
            {"summary": "当前数据不足。", "findings": [], "recommendations": []}
        )

        self.assertEqual(validated["recommendations"], [])

    def test_incomplete_finding_is_rejected(self) -> None:
        """缺少证据字段的 AI 发现不得进入报告。"""

        with self.assertRaisesRegex(ValueError, "缺少字段"):
            validate_ai_result(
                {
                    "summary": "测试总结",
                    "findings": [{"source_id": "traffic", "target": "搜索"}],
                    "recommendations": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
