"""验证周期补查的完整性门槛、数据更新和失败恢复，不访问外部服务。"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.database import Database
from app.jobs.period_analysis import _run_period_pair, run_period_analysis
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskRepository
from test_period_aggregation import daily_row


class PeriodAnalysisJobTest(unittest.TestCase):
    """用独立 SQLite 验证周月报告生命周期。"""

    def setUp(self) -> None:
        """准备临时数据库与仅返回测试结果的 AI 替身。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "data.db")
        self.database.initialize()
        self.reports = ReportRepository(self.database)
        self.tasks = TaskRepository(self.database)
        self.analyzer = Mock(model="test-model", analysis_version="1.0", prompt_hash="test-prompt")
        self.analyzer.analyze.return_value = {
            "summary": {
                "advantage": {"brief": "成交金额领先", "detail": ["周期成交金额领先。"]},
                "weakness": {"brief": "暂无明显短板", "detail": ["当前数据未显示明显短板。"]},
            },
            "findings": [], "recommendations": [],
        }

    def seed_day(self, day: str, status: str = "ready", gmv: float = 700) -> str:
        """写入有部分指标缺失的测试日报，返回报告 ID。"""
        report = daily_row(day, gmv, 100, 10)["report"]
        report["quality_status"] = "partial"
        return self.reports.upsert(None, report, status=status)

    def seed_range(self, start: str, days: int) -> None:
        """按自然日连续写入指定天数的已完成日报。"""
        for offset in range(days):
            self.seed_day((date.fromisoformat(start) + timedelta(days=offset)).isoformat())

    def run_pair(self, start: str, end: str, granularity: str = "week") -> dict:
        """读取测试数据库中的已完成日报并执行一次周期分析。"""
        rows = self.reports.list_ready_day_reports(start, end, "10001", "20001")
        return _run_period_pair(rows, granularity, start, end, self.reports, self.tasks, self.analyzer)

    def test_missing_or_ai_failed_day_blocks_generation_until_ready(self) -> None:
        """六天 ready 与一天缺失或 AI 失败都不生成，七天齐全后正常生成。"""
        self.seed_range("2026-08-31", 6)
        result = self.run_pair("2026-08-31", "2026-09-06")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["missing_days"], ["2026-09-06"])
        self.seed_day("2026-09-06", "ai_failed")
        self.assertEqual(self.run_pair("2026-08-31", "2026-09-06")["status"], "incomplete")
        self.analyzer.analyze.assert_not_called()
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM reports WHERE granularity='week'").fetchone()[0], 0)
        self.seed_day("2026-09-06")
        result = self.run_pair("2026-08-31", "2026-09-06")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["available_days"], 7)
        self.analyzer.analyze.assert_called_once()

    def test_natural_month_requires_all_calendar_days(self) -> None:
        """二月、闰年二月、大小月均要求自然月每一天就绪。"""
        for start, end, days in [
            ("2026-02-01", "2026-02-28", 28),
            ("2024-02-01", "2024-02-29", 29),
            ("2026-04-01", "2026-04-30", 30),
            ("2026-08-01", "2026-08-31", 31),
        ]:
            with self.subTest(start=start):
                self.seed_range(start, days - 1)
                calls = self.analyzer.analyze.call_count
                result = self.run_pair(start, end, "month")
                self.assertEqual(result["status"], "incomplete")
                self.assertEqual(result["missing_days"], [end])
                self.assertEqual(self.analyzer.analyze.call_count, calls)
                self.seed_day(end)
                self.assertEqual(self.run_pair(start, end, "month")["status"], "ready")
                self.assertEqual(self.analyzer.analyze.call_count, calls + 1)

    def test_changed_daily_values_regenerate_same_period_report(self) -> None:
        """日报 ID 不变但数据变化时重新分析，无变化时保留报告和生成时间。"""
        self.seed_range("2026-08-31", 7)
        first = self.run_pair("2026-08-31", "2026-09-06")
        stored = self.reports.get_record(first["report_id"])
        self.assertEqual(self.run_pair("2026-08-31", "2026-09-06")["status"], "existing")
        self.assertEqual(self.reports.get_record(first["report_id"])["updated_at"], stored["updated_at"])
        day_id = self.reports.find_ready_day_report("2026-09-01", "10001", "20001")["report_id"]
        self.assertEqual(self.seed_day("2026-09-01", gmv=1400), day_id)
        second = self.run_pair("2026-08-31", "2026-09-06")
        self.assertEqual(second["status"], "ready")
        self.assertEqual(second["report_id"], first["report_id"])
        self.assertEqual(self.analyzer.analyze.call_count, 2)
        self.assertEqual(self.analyzer.analyze.call_args.args[0]["self_spu_data"]["metrics"]["gmv"], 5600)

    def test_failed_period_retries_ai_with_same_task_and_report(self) -> None:
        """基础日报齐全时可重新执行失败的周期 AI，不重复创建报告或当前任务。"""
        self.seed_range("2026-08-31", 7)
        self.analyzer.analyze.side_effect = RuntimeError("测试 AI 失败")
        failed = self.run_pair("2026-08-31", "2026-09-06")
        self.assertEqual(failed["status"], "ai_failed")
        self.analyzer.analyze.side_effect = None
        success = self.run_pair("2026-08-31", "2026-09-06")
        self.assertEqual(success["status"], "ready")
        self.assertEqual(failed["report_id"], success["report_id"])
        self.assertEqual(failed["analysis_id"], success["analysis_id"])
        self.assertEqual(self.tasks.list_recent()[0]["attempt_count"], 2)

    def test_incomplete_sources_do_not_overwrite_existing_period(self) -> None:
        """已有周报的来源日报未就绪时，只跳过，不覆盖已保存周报。"""
        self.seed_range("2026-08-31", 7)
        first = self.run_pair("2026-08-31", "2026-09-06")
        before = self.reports.get_record(first["report_id"])
        self.seed_day("2026-09-06", "ai_failed")
        self.assertEqual(self.run_pair("2026-08-31", "2026-09-06")["status"], "incomplete")
        self.assertEqual(self.reports.get_record(first["report_id"]), before)
        self.analyzer.analyze.assert_called_once()

    def run_cli(self, start: str) -> tuple[dict, dict]:
        """用隔离配置执行周报 CLI 编排，返回标准摘要与通知结果。"""
        path = self.root / "notification.json"
        args = SimpleNamespace(granularity="week", previous_week=False, start_date=start,
                               self_spu=None, competitor_spu=None, notification_file=path)
        settings = SimpleNamespace(
            database_path=self.root / "data.db", analysis_lock_path=self.root / "analysis.lock",
            deepseek_api_key="test", deepseek_base_url="https://example.invalid",
            deepseek_model="test", deepseek_thinking="enabled",
            deepseek_reasoning_effort="high", deepseek_max_tokens=8192,
            deepseek_timeout_seconds=1, deepseek_max_attempts=1,
            deepseek_pricing_path=self.root / "pricing.json", deepseek_usage_log_dir=self.root / "logs",
        )
        output = io.StringIO()
        with patch("app.jobs.period_analysis.get_settings", return_value=settings), patch(
            "app.jobs.period_analysis.DeepSeekAnalyzer", return_value=self.analyzer
        ), redirect_stdout(output):
            run_period_analysis(args)
        return json.loads(output.getvalue()), json.loads(path.read_text())

    def test_cli_empty_and_incomplete_periods_write_normal_results(self) -> None:
        """没有日报及日报不全均正常退出，并写出宿主机可汇总的周期通知结果。"""
        summary, notification = self.run_cli("2026-08-31")
        self.assertEqual(summary["counts"]["ready"], 0)
        self.assertEqual(notification["results"], [])
        self.assertEqual(notification["granularity"], "week")
        self.seed_range("2026-08-31", 6)
        summary, notification = self.run_cli("2026-08-31")
        self.assertEqual(summary["counts"]["incomplete"], 1)
        self.assertEqual(notification["results"][0]["status"], "incomplete")
        self.assertEqual(notification["results"][0]["end_date"], "2026-09-06")
        self.analyzer.analyze.assert_not_called()
