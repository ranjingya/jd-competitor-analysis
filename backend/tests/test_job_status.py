"""测试日报批处理运行状态。"""

from __future__ import annotations

import asyncio
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.job_status import DailyAnalysisStatusWriter, ensure_status_file_readable, read_daily_analysis_status


class DailyAnalysisStatusTest(unittest.TestCase):
    """验证运行状态可以原子推进并保留终态。"""

    def test_every_atomic_update_publishes_readable_file(self) -> None:
        """严格 umask 下每次发布的状态文件也必须为 0644。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            writer = DailyAnalysisStatusWriter(path)
            replace = os.replace

            def checked_replace(source, target):
                """在原子替换前检查临时文件权限。"""
                self.assertEqual(stat.S_IMODE(Path(source).stat().st_mode), 0o644)
                replace(source, target)

            previous_umask = os.umask(0o077)
            try:
                with patch("app.job_status.os.replace", side_effect=checked_replace) as mocked:
                    writer.start("2026-09-07", ["2026-09-07"])
                    path.chmod(0o600)
                    writer.progress("warehouse_read")
                    writer.complete({"ready": 1})
                    writer.fail(RuntimeError("测试异常"))
                self.assertEqual(mocked.call_count, 4)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            finally:
                os.umask(previous_umask)

    def test_startup_repairs_existing_file_without_changing_content(self) -> None:
        """后端启动修正旧状态文件权限，不改变原有内容和所有者。"""
        from app.main import lifespan, app

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            path.write_text('{"status":"completed"}')
            path.chmod(0o600)
            owner = path.stat().st_uid

            async def start_app():
                """执行一次隔离的应用生命周期。"""
                async with lifespan(app):
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

            with patch("app.main.get_database"), patch(
                "app.main.get_settings", return_value=SimpleNamespace(analysis_status_path=path)
            ):
                asyncio.run(start_app())
            self.assertEqual(path.read_text(), '{"status":"completed"}')
            self.assertEqual(path.stat().st_uid, owner)

    def test_missing_file_permission_check_does_not_create_file(self) -> None:
        """无历史状态时权限检查不创建空状态文件。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            ensure_status_file_readable(path)
            self.assertFalse(path.exists())

    def test_permission_error_is_logged(self) -> None:
        """权限修正失败只记录警告，不阻断 API 启动。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "status.json"
            path.write_text("{}")
            path.chmod(0o600)
            with patch.object(Path, "chmod", side_effect=PermissionError("测试权限错误")):
                with self.assertLogs("app.job_status", level="WARNING") as captured:
                    ensure_status_file_readable(path)
            self.assertIn("状态文件权限设置失败", captured.output[0])

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
        self.assertTrue(completed["completed_at"].endswith("+08:00"))

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
