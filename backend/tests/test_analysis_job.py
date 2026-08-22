"""测试标准化数据、基础报告和 AI 执行记录的数据库编排。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.jobs.analysis import persist_base_report, persist_daily_dataset, start_ai_analysis
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskRepository


class AnalysisJobTest(unittest.TestCase):
    """验证数据集、报告和 AI 执行记录的关联。"""

    def test_dataset_links_report_and_report_links_task(self) -> None:
        """日报关联数据集，AI 执行记录只关联报告。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "data.db")
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
            start_result = start_ai_analysis(
                tasks,
                report_id,
                {"facts": {"dataset_id": dataset_id}},
                "deepseek-v4-pro",
                "1.0",
                "prompt-hash",
            )
            task = tasks.list_recent("processing", 20)[0]
            report_record = reports.get_record(report_id)

        self.assertTrue(start_result.should_execute)
        self.assertEqual(task["analysis_id"], start_result.analysis_id)
        self.assertEqual(task["report_id"], report_id)
        self.assertEqual(task["analysis_version"], "1.0")
        self.assertEqual(task["prompt_hash"], "prompt-hash")
        self.assertEqual(report_record["dataset_id"], dataset_id)


if __name__ == "__main__":
    unittest.main()
