"""测试标准化数据、基础报告和 AI 任务的数据库编排。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.jobs.analysis import enqueue_ai_analysis, persist_base_report, persist_daily_dataset
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskRepository


class AnalysisJobTest(unittest.TestCase):
    """验证同一数据集能够串联报告和 AI 任务。"""

    def test_dataset_report_and_task_share_dataset_id(self) -> None:
        """三个写入步骤应通过相同数据集 ID 建立关联。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "backend.db")
            database.initialize()
            datasets = DatasetRepository(database)
            reports = ReportRepository(database)
            tasks = TaskRepository(database)
            daily_payload = {
                "report_date": "2026-08-18",
                "pair": {
                    "compare_number": "10001+20001",
                    "self_spu": "10001",
                    "competitor_spu": "20001",
                },
                "quality": {"status": "ready"},
            }

            dataset_id = persist_daily_dataset(datasets, daily_payload)
            report_id = persist_base_report(
                reports,
                dataset_id,
                {"meta": {"title": "竞品分析日报"}},
            )
            enqueue_result = enqueue_ai_analysis(
                tasks,
                report_id,
                dataset_id,
                {"facts": {"dataset_id": dataset_id}},
            )
            claimed = tasks.claim("test-worker", lease_seconds=300)
            report_record = reports.get_record(report_id)

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["analysis_id"], enqueue_result.analysis_id)
        self.assertEqual(claimed["dataset_id"], dataset_id)
        self.assertEqual(report_record["dataset_id"], dataset_id)


if __name__ == "__main__":
    unittest.main()
