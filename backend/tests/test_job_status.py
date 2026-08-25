"""测试日报批处理运行状态。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.job_status import DailyAnalysisStatusWriter, read_daily_analysis_status


class DailyAnalysisStatusTest(unittest.TestCase):
    """验证运行状态可以原子推进并保留终态。"""

    def test_missing_status_is_idle(self) -> None:
        """尚未运行日报时应返回稳定空闲状态。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            result = read_daily_analysis_status(Path(temp_dir) / "status.json")

        self.assertEqual(result["status"], "idle")
        self.assertEqual(result["stage"], "idle")
        self.assertFalse(result["process_alive"])
        self.assertFalse(result["stale"])

    def test_progress_and_completion_are_persisted(self) -> None:
        """运行阶段、商品对、进度计数和成功终态都应持久化。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            writer = DailyAnalysisStatusWriter(path)
            writer.start("2026-08-24", ["2026-08-24", "2026-08-23"])
            writer.progress(
                "deepseek_analysis",
                current_date="2026-08-24",
                self_spu="10001",
                competitor_spu="20001",
                completed_items=1,
                total_items=4,
            )
            running = read_daily_analysis_status(path)
            writer.complete({"ready": 4})
            completed = read_daily_analysis_status(path)

        self.assertEqual(running["status"], "running")
        self.assertEqual(running["stage"], "deepseek_analysis")
        self.assertEqual(running["self_spu"], "10001")
        self.assertEqual(running["completed_items"], 1)
        self.assertEqual(running["total_items"], 4)
        self.assertTrue(running["process_alive"])
        self.assertFalse(running["stale"])
        self.assertEqual(completed["run_id"], running["run_id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["counts"], {"ready": 4})
        self.assertIsNotNone(completed["completed_at"])

    def test_failure_keeps_last_business_stage(self) -> None:
        """失败状态应保留退出前的最后业务阶段和错误摘要。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            writer = DailyAnalysisStatusWriter(path)
            writer.start("2026-08-24", ["2026-08-24"])
            writer.progress("warehouse_read", current_date="2026-08-24")
            writer.fail(RuntimeError("数仓连接中断"))
            result = read_daily_analysis_status(path)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stage"], "failed")
        self.assertEqual(result["last_stage"], "warehouse_read")
        self.assertEqual(result["error"]["type"], "RuntimeError")
        self.assertEqual(result["error"]["message"], "数仓连接中断")
        self.assertFalse(result["process_alive"])
        self.assertFalse(result["stale"])

    def test_running_status_without_process_is_stale(self) -> None:
        """运行状态对应进程不存在时应直接标记为陈旧。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            path.write_text(
                """{
  "schema_version": "1.0",
  "status": "running",
  "stage": "warehouse_read",
  "pid": 99999999,
  "progress_at": "2026-08-25T08:00:00+00:00"
}
""",
                encoding="utf-8",
            )
            result = read_daily_analysis_status(path)

        self.assertFalse(result["process_alive"])
        self.assertTrue(result["stale"])


if __name__ == "__main__":
    unittest.main()
