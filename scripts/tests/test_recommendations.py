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
        """没有证据充分的劣势时允许写入空数组。"""

        self.assertEqual(validate_recommendations([]), [])

    def test_accepts_warning_recommendation(self) -> None:
        """状态为 warning 的完整建议可以通过校验。"""

        item = _warning_item()
        self.assertEqual(validate_recommendations([item]), [item])

    def test_rejects_non_warning_recommendation(self) -> None:
        """优势或中性建议不能写入劣势建议数组。"""

        item = _warning_item()
        item["status"] = "advantage"
        with self.assertRaisesRegex(ValueError, "状态必须为 warning"):
            validate_recommendations([item])

    def test_rejects_more_than_five_recommendations(self) -> None:
        """劣势建议数量不能超过五条。"""

        with self.assertRaisesRegex(ValueError, "0–5"):
            validate_recommendations([_warning_item() for _ in range(6)])


if __name__ == "__main__":
    unittest.main()
