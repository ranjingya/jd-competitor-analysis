"""测试报告差值和差距幅度字段。"""

from __future__ import annotations

import unittest

from jd_competitor_analysis.report import (
    _highlight_gap_fields,
    build_core_views,
    relative_gap_pct,
)


class ReportGapTest(unittest.TestCase):
    """验证核心指标和来源重点卡使用同一套差距规则。"""

    def test_relative_gap_uses_competitor_as_denominator(self) -> None:
        """差距幅度必须按竞品值计算，并保留正负方向。"""

        self.assertAlmostEqual(relative_gap_pct(300, 200), 50.0)
        self.assertAlmostEqual(relative_gap_pct(150, 200), -25.0)
        self.assertIsNone(relative_gap_pct(100, 0))

    def test_core_cards_use_percentage_point_for_conversion(self) -> None:
        """成交转化率只保存本品减竞品的百分点差。"""

        core = {
            "self_values": {
                "gmv": 300.0,
                "sold_units": 30.0,
                "orders": 20.0,
                "views": 1000.0,
                "visitors": 150.0,
                "cart_users": 50.0,
                "conversion_rate": 0.15,
                "customer_price": 50.0,
            },
            "final_values": {
                "gmv": 200.0,
                "sold_units": 20.0,
                "orders": 10.0,
                "views": 800.0,
                "visitors": 200.0,
                "cart_users": 40.0,
                "conversion_rate": 0.20,
                "customer_price": 100.0,
            },
        }

        _, cards = build_core_views(core)
        card_map = {item["id"]: item for item in cards}

        self.assertEqual(card_map["gmv"]["gap_value"], 100.0)
        self.assertEqual(card_map["gmv"]["gap_rate_pct"], 50.0)
        self.assertEqual(card_map["visitors"]["gap_rate_pct"], -25.0)
        self.assertAlmostEqual(card_map["conversion_rate"]["gap_value"], -5.0)
        self.assertIsNone(card_map["conversion_rate"]["gap_rate_pct"])
        self.assertEqual(card_map["conversion_rate"]["gap_mode"], "percentage_point")
        self.assertNotIn("+", card_map["gmv"]["gap_text"])
        self.assertNotIn("x", card_map["gmv"]["gap_text"])

    def test_highlight_fields_label_metric_and_preserve_negative_rate(self) -> None:
        """来源重点卡必须明确指标名称并保留负向幅度。"""

        fields = _highlight_gap_fields("访客", 150.0, 200.0)

        self.assertEqual(fields["metric_label"], "访客")
        self.assertEqual(fields["gap_value"], -50.0)
        self.assertEqual(fields["gap_rate_pct"], -25.0)
        self.assertEqual(fields["gap_mode"], "relative")


if __name__ == "__main__":
    unittest.main()
