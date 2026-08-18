"""测试报告 API 数据仓库。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.repositories.report_repository import ReportRepository


class ReportRepositoryTest(unittest.TestCase):
    """验证空索引、路径转换和安全读取。"""

    def test_empty_index_and_legacy_path_conversion(self) -> None:
        """无报告时返回空结构，旧静态路径应转换为 API 路径。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            repository = ReportRepository(reports_dir)
            self.assertEqual(repository.read_index()["reports"]["day"], [])

            index = {
                "schema_version": "1.0",
                "reports": {
                    "day": [
                        {
                            "period_key": "day:2026-08-17",
                            "path": "/reports/day/2026-08-17/analysis_result.json",
                        }
                    ],
                    "week": [],
                    "month": [],
                },
            }
            (reports_dir / "report-index.json").write_text(
                json.dumps(index, ensure_ascii=False),
                encoding="utf-8",
            )
            converted = repository.read_index()

        self.assertEqual(converted["reports"]["day"][0]["path"], "/api/reports/day/2026-08-17")

    def test_current_api_path_is_preserved(self) -> None:
        """当前 API 路径应直接解析周期目录，不依赖周期键格式。"""

        entry = {
            "period_key": "day:2026-08-17_2026-08-17",
            "path": "/api/reports/day/2026-08-17",
        }

        self.assertEqual(ReportRepository._period_directory_from_entry(entry), "2026-08-17")

    def test_report_path_is_validated(self) -> None:
        """报告读取不得接受目录穿越路径。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            repository = ReportRepository(Path(temp_dir))
            with self.assertRaisesRegex(ValueError, "格式无效"):
                repository.read_report("day", "../../.env")


if __name__ == "__main__":
    unittest.main()
