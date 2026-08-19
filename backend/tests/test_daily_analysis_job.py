"""测试正式日数据分析入库编排。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.database import Database
from app.jobs.daily_analysis import process_daily_pair, process_daily_pairs
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskRepository
from jd_competitor_analysis.warehouse_sources import ProductPair


def dataset_payload(status: str = "partial") -> dict[str, object]:
    """生成可写入数据库的最小标准化数据集。"""

    return {
        "report_date": "2026-08-18",
        "pair": {
            "compare_number": "10001+20001",
            "self_spu": "10001",
            "competitor_spu": "20001",
        },
        "self_product": {
            "sku_components": [],
            "quality": {"status": "partial"},
        },
        "sources": {},
        "quality": {"status": status, "issues": []},
    }


class DailyAnalysisJobTest(unittest.TestCase):
    """验证单商品对写入和批量跳过规则。"""

    def setUp(self) -> None:
        """创建统一测试数据库和仓库。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "backend.db")
        self.database.initialize()
        self.datasets = DatasetRepository(self.database)
        self.reports = ReportRepository(self.database)
        self.tasks = TaskRepository(self.database)
        self.pair = ProductPair.parse("10001+20001")

    def tearDown(self) -> None:
        """清理测试数据库。"""

        self.temporary_directory.cleanup()

    @patch("app.jobs.daily_analysis.build_ai_task_payload")
    @patch("app.jobs.daily_analysis.analyze_daily_dataset")
    @patch("app.jobs.daily_analysis.build_daily_dataset")
    def test_pair_writes_dataset_report_and_task(
        self,
        build_dataset: Mock,
        analyze_dataset: Mock,
        build_task_payload: Mock,
    ) -> None:
        """有效数据应依次写入数据集、报告和 AI 任务。"""

        build_dataset.return_value = dataset_payload()
        analyze_dataset.return_value = {"meta": {"title": "日报"}, "ai_recommendations": []}
        build_task_payload.return_value = {"facts": {"metric": 1}}

        result = process_daily_pair(
            Mock(),
            Mock(),
            self.pair,
            "2026-08-18",
            self.datasets,
            self.reports,
            self.tasks,
            product_images={},
        )
        claimed = self.tasks.claim("test-worker", lease_seconds=300)

        self.assertEqual(result["status"], "pending_ai")
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["dataset_id"], result["dataset_id"])
        self.assertEqual(self.reports.get_record(result["report_id"])["dataset_id"], result["dataset_id"])

    @patch("app.jobs.daily_analysis.analyze_daily_dataset")
    @patch("app.jobs.daily_analysis.build_daily_dataset")
    def test_invalid_dataset_is_stored_without_report_or_task(
        self,
        build_dataset: Mock,
        analyze_dataset: Mock,
    ) -> None:
        """本品或核心事实无效时只保留数据集用于排查。"""

        build_dataset.return_value = dataset_payload("invalid")

        result = process_daily_pair(
            Mock(),
            Mock(),
            self.pair,
            "2026-08-18",
            self.datasets,
            self.reports,
            self.tasks,
        )

        self.assertEqual(result["status"], "invalid")
        self.assertIsNone(result["report_id"])
        self.assertIsNone(self.tasks.claim("test-worker", lease_seconds=300))
        analyze_dataset.assert_not_called()

    @patch("app.jobs.daily_analysis.process_daily_pair")
    def test_missing_core_pair_is_skipped_without_stopping_batch(self, process_pair: Mock) -> None:
        """核心表找不到的商品对应跳过并继续下一组。"""

        process_pair.side_effect = [
            LookupError("核心指标表没有商品对日数据"),
            {
                "compare_number": "10002+20002",
                "status": "pending_ai",
                "quality_status": "ready",
                "dataset_id": "dataset-2",
                "report_id": "report-2",
                "analysis_id": "task-2",
            },
        ]
        results = process_daily_pairs(
            Mock(),
            Mock(),
            [self.pair, ProductPair.parse("10002+20002")],
            "2026-08-18",
            self.database,
        )

        self.assertEqual([item["status"] for item in results], ["skipped", "pending_ai"])
        self.assertEqual(process_pair.call_count, 2)


if __name__ == "__main__":
    unittest.main()
