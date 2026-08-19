"""测试 AI 任务接口的空队列语义。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import Response, status

from app.api.analysis_tasks import claim_task
from app.config import Settings
from app.repositories.task_repository import TaskRepository
from app.schemas import ClaimRequest


class AnalysisTaskApiTest(unittest.TestCase):
    """验证任务接口在空队列时返回标准 204 响应。"""

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
