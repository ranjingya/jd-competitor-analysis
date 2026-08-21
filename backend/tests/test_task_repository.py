"""测试后端内部 AI 执行记录。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskRepository


class TaskRepositoryTest(unittest.TestCase):
    """验证内部 AI 执行的完成、重试和版本替换。"""

    def setUp(self) -> None:
        """创建独立数据库及有效基础报告。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "backend.db")
        datasets = DatasetRepository(self.database)
        datasets.initialize()
        self.dataset_id = datasets.store(
            {
                "report_date": "2026-08-11",
                "pair": {
                    "compare_number": "10001+20001",
                    "self_spu": "10001",
                    "competitor_spu": "20001",
                },
                "quality": {"status": "ready"},
            },
            dataset_id="dataset-1",
        )
        report_path = Path(__file__).resolve().parents[1] / "assets" / "analysis-result.example.json"
        self.base_report = json.loads(report_path.read_text(encoding="utf-8"))
        self.base_report["ai_recommendations"] = []
        self.reports = ReportRepository(self.database)
        self.report_id = self.reports.upsert(
            self.dataset_id,
            self.base_report,
            report_id="report-1",
        )
        self.repository = TaskRepository(self.database)
        self.result = {
            "summary": {
                "advantage": {"brief": "流量规模领先", "detail": ["本品流量规模领先。"]},
                "weakness": {"brief": "转化效率落后", "detail": ["本品转化效率落后。"]},
            },
            "findings": [
                {
                    "source_id": "traffic",
                    "target": "搜索渠道",
                    "judgement": "访客存在差距",
                    "evidence": "本品访客低于竞品估算值",
                }
            ],
            "recommendations": [],
        }

    def tearDown(self) -> None:
        """清理测试数据库。"""

        self.temporary_directory.cleanup()

    def test_start_and_complete_merge_report(self) -> None:
        """新执行应直接进入 processing，完成后合并报告。"""

        started = self.repository.start(
            self.report_id,
            self.dataset_id,
            "hash-1",
            {"metric": 12},
            "deepseek-v4-pro",
            analysis_id="task-1",
        )
        self.repository.complete(started.analysis_id, self.result)

        task = self.repository.list_recent("completed", 20)[0]
        report = self.reports.get_record(self.report_id)
        self.assertTrue(started.should_execute)
        self.assertEqual(task["model"], "deepseek-v4-pro")
        self.assertEqual(task["attempt_count"], 1)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["report"]["meta"]["summary"], "流量规模领先")
        self.assertEqual(report["report"]["meta"]["weakness_summary"], "转化效率落后")

    def test_completed_same_input_is_reused(self) -> None:
        """相同输入已完成时不应再次调用模型。"""

        first = self.repository.start(
            self.report_id, self.dataset_id, "same-hash", {"metric": 1}, "deepseek-v4-pro"
        )
        self.repository.complete(first.analysis_id, self.result)
        second = self.repository.start(
            self.report_id, self.dataset_id, "same-hash", {"metric": 1}, "deepseek-v4-pro"
        )

        self.assertEqual(second.analysis_id, first.analysis_id)
        self.assertFalse(second.should_execute)

    def test_failed_same_input_retries_same_record(self) -> None:
        """相同输入失败后应复用记录并增加尝试次数。"""

        first = self.repository.start(
            self.report_id, self.dataset_id, "retry-hash", {"metric": 2}, "deepseek-v4-pro"
        )
        self.repository.fail(first.analysis_id, "模型超时")
        second = self.repository.start(
            self.report_id, self.dataset_id, "retry-hash", {"metric": 2}, "deepseek-v4-pro"
        )

        task = self.repository.list_recent("processing", 20)[0]
        self.assertEqual(second.analysis_id, first.analysis_id)
        self.assertTrue(second.should_execute)
        self.assertEqual(task["attempt_count"], 2)
        self.assertIsNone(task["error_message"])

    def test_new_input_expires_completed_record(self) -> None:
        """同一报告的新输入应使旧执行过期。"""

        first = self.repository.start(
            self.report_id, self.dataset_id, "old-hash", {"version": 1}, "deepseek-v4-pro"
        )
        self.repository.complete(first.analysis_id, self.result)
        current = self.repository.start(
            self.report_id, self.dataset_id, "new-hash", {"version": 2}, "deepseek-v4-pro"
        )

        self.assertNotEqual(current.analysis_id, first.analysis_id)
        self.assertEqual(self.repository.list_recent("expired", 20)[0]["analysis_id"], first.analysis_id)

    def test_fail_marks_report_ai_failed(self) -> None:
        """模型失败时报告应同步标记为 ai_failed。"""

        started = self.repository.start(
            self.report_id, self.dataset_id, "failed-hash", {"metric": 3}, "deepseek-v4-pro"
        )
        self.repository.fail(started.analysis_id, "分析证据不足")

        self.assertEqual(self.reports.get_record(self.report_id)["status"], "ai_failed")

    def test_week_report_task_does_not_require_dataset(self) -> None:
        """周报 AI 执行应仅通过报告关联，并允许数据集 ID 为空。"""

        weekly_report = json.loads(json.dumps(self.base_report))
        weekly_report["meta"].update(
            {
                "granularity": "week",
                "period_start": "2026-08-10",
                "period_end": "2026-08-16",
            }
        )
        weekly_report_id = self.reports.upsert(
            None,
            weekly_report,
            report_id="report-week",
        )

        started = self.repository.start(
            weekly_report_id,
            None,
            "week-hash",
            {"period": "2026-08-10_2026-08-16"},
            "deepseek-v4-pro",
            analysis_id="task-week",
        )
        self.repository.complete(started.analysis_id, self.result)

        task = self.repository.list_recent("completed", 20)[0]
        self.assertIsNone(task["dataset_id"])
        self.assertEqual(task["granularity"], "week")
        self.assertEqual(self.reports.get_record(weekly_report_id)["status"], "ready")


if __name__ == "__main__":
    unittest.main()
