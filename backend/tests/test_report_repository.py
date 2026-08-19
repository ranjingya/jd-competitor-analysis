"""测试数据库报告仓库。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository


class ReportRepositoryTest(unittest.TestCase):
    """验证报告写入、更新、索引和兼容读取。"""

    def setUp(self) -> None:
        """创建统一数据库和一份标准化数据集。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "backend.db"
        datasets = DatasetRepository(database_path)
        datasets.initialize()
        self.dataset_id = datasets.store(
            {
                "report_date": "2026-08-17",
                "pair": {
                    "compare_number": "10001+20001",
                    "self_spu": "10001",
                    "competitor_spu": "20001",
                },
                "quality": {"status": "partial"},
            },
            dataset_id="dataset-1",
        )
        self.repository = ReportRepository(database_path)

    def tearDown(self) -> None:
        """清理测试数据库。"""

        self.temporary_directory.cleanup()

    def test_empty_index_and_report_upsert(self) -> None:
        """空库返回稳定索引，同一数据集重复写入应更新原报告。"""

        self.assertEqual(self.repository.read_index()["reports"]["day"], [])
        report_id = self.repository.upsert(
            self.dataset_id,
            {"meta": {"title": "日报", "summary": "基础报告"}},
            report_id="report-1",
        )
        repeated_id = self.repository.upsert(
            self.dataset_id,
            {"meta": {"title": "日报", "summary": "AI 已完成"}},
            status="ready",
            report_id="report-other",
        )

        self.assertEqual(report_id, "report-1")
        self.assertEqual(repeated_id, "report-1")
        self.assertEqual(self.repository.get("report-1")["meta"]["summary"], "AI 已完成")
        entry = self.repository.read_index()["reports"]["day"][0]
        self.assertEqual(entry["path"], "/api/reports/report-1")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(entry["quality_status"], "partial")

    def test_legacy_day_lookup_and_invalid_path(self) -> None:
        """日报可按旧日期路径读取，目录穿越应被拒绝。"""

        self.repository.upsert(self.dataset_id, {"meta": {"title": "日报"}}, report_id="report-1")

        self.assertEqual(
            self.repository.read_report("day", "2026-08-17")["meta"]["title"],
            "日报",
        )
        with self.assertRaisesRegex(ValueError, "格式无效"):
            self.repository.read_report("day", "../../.env")


if __name__ == "__main__":
    unittest.main()
