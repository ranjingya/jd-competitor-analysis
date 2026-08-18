"""测试 AI 分析任务的持久化和租约约束。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.repositories.task_repository import TaskConflictError, TaskRepository


class TaskRepositoryTest(unittest.TestCase):
    """验证任务领取、完成、幂等和租约冲突。"""

    def setUp(self) -> None:
        """为每个测试创建独立数据库。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "tasks.db"
        self.repository = TaskRepository(database_path)
        self.repository.initialize()

    def tearDown(self) -> None:
        """清理测试数据库。"""

        self.temporary_directory.cleanup()

    def test_claim_and_complete_are_persistent_and_idempotent(self) -> None:
        """任务应被领取、完成，并允许相同结果重复提交。"""

        analysis_id = self.repository.enqueue("hash-1", {"metric": 12}, analysis_id="task-1")
        claimed = self.repository.claim("mac-worker", lease_seconds=300)

        self.assertEqual(analysis_id, "task-1")
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["payload"], {"metric": 12})
        result = {"summary": "存在流量差距", "findings": [], "recommendations": []}
        self.repository.complete(
            analysis_id,
            claimed["source_hash"],
            claimed["lease_token"],
            result,
        )
        self.repository.complete(
            analysis_id,
            claimed["source_hash"],
            claimed["lease_token"],
            result,
        )
        self.assertIsNone(self.repository.claim("mac-worker", lease_seconds=300))

    def test_complete_rejects_wrong_lease(self) -> None:
        """错误租约不得写入 AI 分析结果。"""

        self.repository.enqueue("hash-2", {"metric": 8}, analysis_id="task-2")
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

        first_id = self.repository.enqueue("same-hash", {"metric": 1}, analysis_id="task-first")
        second_id = self.repository.enqueue("same-hash", {"metric": 1}, analysis_id="task-second")

        self.assertEqual(first_id, "task-first")
        self.assertEqual(second_id, "task-first")


if __name__ == "__main__":
    unittest.main()
