"""测试 AI 劣势建议的结构校验。"""

from __future__ import annotations

import unittest

from jd_competitor_analysis.recommendations import validate_recommendations


def _warning_item() -> dict[str, object]:
    """生成一条结构完整的劣势建议测试数据。"""

    return {
        "source_id": "traffic",
        "source_label": "流量来源",
        "target": "站内场域",
        "status": "warning",
        "evidence": "本品转化率低于竞品准真实估算值。",
        "actions": ["检查商品首屏到支付前的承接损耗。"],
        "validation": "下一周期复核转化率是否高于当前基线。",
    }


class RecommendationValidationTest(unittest.TestCase):
    """验证劣势建议的数量和状态约束。"""

    def test_accepts_empty_recommendations(self) -> None:
        """无符合 SOP 的动作时允许空数组。"""
        self.assertEqual(validate_recommendations([]), [])

    def test_accepts_multiple_source_recommendations(self) -> None:
        """覆盖多个来源的多条 warning 建议可以通过校验。"""

        traffic_item = _warning_item()
        keyword_item = {
            **_warning_item(),
            "source_id": "keywords",
            "source_label": "关键词",
            "target": "儿童遮阳帽",
        }
        self.assertEqual(
            validate_recommendations([traffic_item, keyword_item]),
            [traffic_item, keyword_item],
        )

    def test_accepts_single_recommendation(self) -> None:
        """单条符合条件的建议可以保存。"""
        self.assertEqual(len(validate_recommendations([_warning_item()])), 1)

    def test_accepts_single_source_recommendations(self) -> None:
        """建议允许全部来自同一个模块。"""
        self.assertEqual(len(validate_recommendations([_warning_item(), _warning_item()])), 2)

    def test_rejects_non_warning_recommendation(self) -> None:
        """优势或中性建议不能写入劣势建议数组。"""

        item = _warning_item()
        item["status"] = "advantage"
        keyword_item = {
            **_warning_item(),
            "source_id": "keywords",
            "source_label": "关键词",
            "target": "儿童遮阳帽",
        }
        with self.assertRaisesRegex(ValueError, "状态必须为 warning"):
            validate_recommendations([item, keyword_item])

    def test_accepts_more_than_five_recommendations(self) -> None:
        """符合规则的建议可超过五条。"""

        items = []
        for index in range(6):
            item = _warning_item()
            item["source_id"] = "traffic" if index % 2 == 0 else "keywords"
            items.append(item)
        self.assertEqual(validate_recommendations(items), items)


if __name__ == "__main__":
    unittest.main()
