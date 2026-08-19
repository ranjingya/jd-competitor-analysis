"""测试 AI 分析任务的持久化和租约约束。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskConflictError, TaskRepository


class TaskRepositoryTest(unittest.TestCase):
    """验证任务领取、完成、幂等和租约冲突。"""

    def setUp(self) -> None:
        """为每个测试创建独立数据库。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "backend.db"
        self.database = Database(database_path)
        dataset_repository = DatasetRepository(self.database)
        dataset_repository.initialize()
        self.dataset_id = dataset_repository.store(
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
        self.report_repository = ReportRepository(self.database)
        report_path = Path(__file__).resolve().parents[1] / "assets" / "analysis-result.example.json"
        base_report = json.loads(report_path.read_text(encoding="utf-8"))
        base_report["ai_recommendations"] = []
        self.report_id = self.report_repository.upsert(
            self.dataset_id,
            base_report,
            report_id="report-1",
        )
        self.repository = TaskRepository(self.database)

    def tearDown(self) -> None:
        """清理测试数据库。"""

        self.temporary_directory.cleanup()

    def test_claim_and_complete_are_persistent_and_idempotent(self) -> None:
        """任务应被领取、完成，并允许相同结果重复提交。"""

        enqueue_result = self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "hash-1",
            {"metric": 12},
            analysis_id="task-1",
        )
        claimed = self.repository.claim("mac-worker", lease_seconds=300)

        self.assertEqual(enqueue_result.analysis_id, "task-1")
        self.assertTrue(enqueue_result.created)
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["dataset_id"], self.dataset_id)
        self.assertEqual(claimed["report_id"], self.report_id)
        self.assertEqual(claimed["report_date"], "2026-08-11")
        self.assertEqual(claimed["compare_number"], "10001+20001")
        self.assertEqual(claimed["self_spu"], "10001")
        self.assertEqual(claimed["competitor_spu"], "20001")
        self.assertEqual(claimed["attempt_count"], 1)
        self.assertTrue(claimed["created_at"])
        self.assertEqual(claimed["payload"], {"metric": 12})
        result = {
            "summary": "存在流量差距",
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
        self.repository.complete(
            enqueue_result.analysis_id,
            claimed["source_hash"],
            claimed["lease_token"],
            result,
        )
        self.repository.complete(
            enqueue_result.analysis_id,
            claimed["source_hash"],
            claimed["lease_token"],
            result,
        )
        self.assertIsNone(self.repository.claim("mac-worker", lease_seconds=300))
        report_record = self.report_repository.get_record(self.report_id)
        self.assertEqual(report_record["status"], "ready")
        self.assertEqual(report_record["report"]["meta"]["summary"], "存在流量差距")
        self.assertEqual(report_record["report"]["ai_findings"], result["findings"])

    def test_list_recent_returns_visible_metadata_and_supports_status_filter(self) -> None:
        """任务列表应展示生成时间、商品对和状态，并支持状态筛选。"""

        self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "hash-visible",
            {"secret_fact": 12},
            analysis_id="task-visible",
        )

        pending_tasks = self.repository.list_recent(status="pending", limit=20)
        completed_tasks = self.repository.list_recent(status="completed", limit=20)

        self.assertEqual(len(pending_tasks), 1)
        self.assertEqual(completed_tasks, [])
        task = pending_tasks[0]
        self.assertEqual(task["analysis_id"], "task-visible")
        self.assertEqual(task["report_date"], "2026-08-11")
        self.assertEqual(task["compare_number"], "10001+20001")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["attempt_count"], 0)
        self.assertTrue(task["created_at"])
        self.assertNotIn("payload", task)
        self.assertNotIn("lease_token", task)
        self.assertNotIn("result", task)

    def test_complete_rejects_wrong_lease(self) -> None:
        """错误租约不得写入 AI 分析结果。"""

        self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "hash-2",
            {"metric": 8},
            analysis_id="task-2",
        )
        claimed = self.repository.claim("mac-worker", lease_seconds=300)
        assert claimed is not None

        with self.assertRaisesRegex(TaskConflictError, "租约无效"):
            self.repository.complete(
                "task-2",
                claimed["source_hash"],
                "wrong-lease",
                {"summary": "无效结果"},
            )

    def test_enqueue_reuses_same_source_hash(self) -> None:
        """相同数据版本不得重复创建 AI 分析任务。"""

        first_id = self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "same-hash",
            {"metric": 1},
            analysis_id="task-first",
        )
        second_id = self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "same-hash",
            {"metric": 1},
            analysis_id="task-second",
        )

        self.assertEqual(first_id.analysis_id, "task-first")
        self.assertTrue(first_id.created)
        self.assertEqual(second_id.analysis_id, "task-first")
        self.assertFalse(second_id.created)

    def test_new_input_expires_old_task_and_rejects_old_lease(self) -> None:
        """同一报告的新输入应替代旧任务，旧租约不得继续回传。"""

        self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "old-hash",
            {"version": "old"},
            analysis_id="task-old",
        )
        old_task = self.repository.claim("mac-worker", lease_seconds=300)
        assert old_task is not None

        new_result = self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "new-hash",
            {"version": "new"},
            analysis_id="task-new",
        )

        with self.assertRaisesRegex(TaskConflictError, "expired"):
            self.repository.complete(
                "task-old",
                old_task["source_hash"],
                old_task["lease_token"],
                {"summary": "迟到结果", "findings": [], "recommendations": []},
            )
        new_task = self.repository.claim("mac-worker", lease_seconds=300)
        assert new_task is not None
        self.assertEqual(new_result.analysis_id, "task-new")
        self.assertEqual(new_task["analysis_id"], "task-new")
        self.assertEqual(self.repository.list_recent("expired", 20)[0]["analysis_id"], "task-old")

    def test_new_input_expires_previously_completed_task(self) -> None:
        """已完成任务遇到同一报告的新输入时也应转为 expired。"""

        self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "completed-hash",
            {"version": "completed"},
            analysis_id="task-completed",
        )
        completed_task = self.repository.claim("mac-worker", lease_seconds=300)
        assert completed_task is not None
        self.repository.complete(
            "task-completed",
            completed_task["source_hash"],
            completed_task["lease_token"],
            {"summary": "旧结论", "findings": [], "recommendations": []},
        )

        current = self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "current-hash",
            {"version": "current"},
            analysis_id="task-current",
        )

        self.assertEqual(current.analysis_id, "task-current")
        self.assertEqual(
            self.repository.list_recent("expired", 20)[0]["analysis_id"],
            "task-completed",
        )
        self.assertEqual(
            self.repository.list_recent("pending", 20)[0]["analysis_id"],
            "task-current",
        )

    def test_fail_marks_report_ai_failed(self) -> None:
        """AI 失败时任务和所属报告应同步进入失败状态。"""

        self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "hash-failed",
            {"metric": 3},
            analysis_id="task-failed",
        )
        claimed = self.repository.claim("mac-worker", lease_seconds=300)
        assert claimed is not None

        self.repository.fail("task-failed", claimed["lease_token"], "分析证据不足")

        self.assertEqual(self.report_repository.get_record(self.report_id)["status"], "ai_failed")

    def test_invalid_ai_result_rolls_back_task_and_report(self) -> None:
        """报告合并失败时任务完成状态也必须回滚。"""

        self.repository.enqueue(
            self.report_id,
            self.dataset_id,
            "hash-invalid-result",
            {"metric": 4},
            analysis_id="task-invalid-result",
        )
        claimed = self.repository.claim("mac-worker", lease_seconds=300)
        assert claimed is not None

        with self.assertRaisesRegex(ValueError, "缺少字段"):
            self.repository.complete(
                "task-invalid-result",
                claimed["source_hash"],
                claimed["lease_token"],
                {
                    "summary": "无效结果",
                    "findings": [{"source_id": "traffic"}],
                    "recommendations": [],
                },
            )

        with self.database.connection() as connection:
            task_status = connection.execute(
                "SELECT status FROM analysis_tasks WHERE analysis_id = 'task-invalid-result'"
            ).fetchone()["status"]
        self.assertEqual(task_status, "processing")
        self.assertEqual(self.report_repository.get_record(self.report_id)["status"], "pending_ai")


if __name__ == "__main__":
    unittest.main()
