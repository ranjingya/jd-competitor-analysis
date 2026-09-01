"""测试项目统一北京时间工具。"""

from __future__ import annotations

import unittest
from datetime import datetime

from jd_competitor_analysis.time_utils import (
    beijing_now_text,
    normalize_beijing_time_text,
)


class TimeUtilsTest(unittest.TestCase):
    """验证时间生成与历史值转换均使用东八区。"""

    def test_beijing_now_text_contains_positive_eight_offset(self) -> None:
        """当前时间文本应明确携带 `+08:00`。"""

        value = beijing_now_text()

        self.assertTrue(value.endswith("+08:00"))
        self.assertIsNotNone(datetime.fromisoformat(value).tzinfo)

    def test_normalize_converts_utc_and_naive_values(self) -> None:
        """UTC 历史值应换算，无偏移历史值应按北京时间解释。"""

        self.assertEqual(
            normalize_beijing_time_text("2026-08-27T07:27:11+00:00"),
            "2026-08-27T15:27:11+08:00",
        )
        self.assertEqual(
            normalize_beijing_time_text("2026-08-27T15:27:11"),
            "2026-08-27T15:27:11+08:00",
        )


if __name__ == "__main__":
    unittest.main()
