"""测试 AI 任务列表和空队列接口语义。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import Response, status

from app.api.analysis_tasks import claim_task, list_tasks
from app.config import Settings
from app.repositories.task_repository import TaskRepository
from app.schemas import ClaimRequest


class AnalysisTaskApiTest(unittest.TestCase):
    """验证任务列表和空队列响应。"""

    def test_list_returns_empty_task_summary(self) -> None:
        """空数据库应返回可直接展示的空任务列表。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            repository = TaskRepository(Path(temp_dir) / "backend.db")
            repository.initialize()

            response = list_tasks(None, 20, repository)

        self.assertEqual(response.count, 0)
        self.assertEqual(response.tasks, [])

    def test_claim_returns_empty_response_when_queue_is_empty(self) -> None:
        """空队列不得触发响应模型校验错误。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = TaskRepository(root / "backend.db")
            repository.initialize()
            settings = Settings(
                database_path=root / "backend.db",
                ai_worker_token="test-token",
                task_lease_seconds=300,
            )

            response = claim_task(ClaimRequest(worker_id="test-mac"), settings, repository)

        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


if __name__ == "__main__":
    unittest.main()
