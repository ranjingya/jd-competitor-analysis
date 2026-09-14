"""使用隔离数据库验证仅重跑 AI 的命令流程。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.database import Database
from app.jobs.reanalyze import reanalyze_reports
from app.repositories.report_repository import ReportRepository
from report_fixture import build_report_fixture


class ReanalyzeTest(unittest.TestCase):
    """验证筛选、强制调用和基础字段保留。"""

    def setUp(self):
        """创建隔离报告与 AI 替身。"""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "data.db"
        self.db = Database(self.path)
        self.db.initialize()
        self.repo = ReportRepository(self.db)
        self.rid = self.repo.upsert(None, build_report_fixture("2026-08-11"), status="ready")
        self.other = self.repo.upsert(None, build_report_fixture("2026-08-12"), status="ready")
        self.ai = Mock(model="test", analysis_version="1", prompt_hash="test")
        self.ai.analyze.return_value = {
            "summary": {"advantage": {"brief": "新优势", "detail": ["新优势详情"]},
                        "weakness": {"brief": "新弱点", "detail": ["新弱点详情"]}},
            "findings": [], "recommendations": [],
        }

    def snapshot(self, rid):
        """读取数据库中的原始报告字段。"""
        with self.db.connection() as con:
            return dict(con.execute("SELECT * FROM reports WHERE report_id=?", (rid,)).fetchone())

    def test_force_twice_preserves_base_and_other_dates(self):
        """重复调用仍生成 AI，基础字段和其他日期逐字段不变。"""
        before, other = self.snapshot(self.rid), self.snapshot(self.other)
        for _ in range(2):
            self.assertEqual(reanalyze_reports(self.path, "2026-08-11", self.ai, "10001", "20001"),
                             {"ready": 1, "failed": 0})
        self.assertEqual(self.ai.analyze.call_count, 2)
        after = self.snapshot(self.rid)
        allowed = {"advantage_summary", "weakness_summary", "advantage_detail_json", "weakness_detail_json",
                   "ai_findings_json", "ai_recommendations_json", "updated_at", "status"}
        for key in before.keys() - allowed:
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(other, self.snapshot(self.other))
        payload = self.ai.analyze.call_args.args[0]
        self.assertNotIn("summary", payload)
        self.assertNotIn("ai_recommendations", payload)
        self.assertEqual(after["advantage_summary"], "新优势")

    def test_failure_preserves_base(self):
        """失败记录状态但不清空基础指标。"""
        before = self.snapshot(self.rid)
        self.ai.analyze.side_effect = RuntimeError("模拟失败")
        self.assertEqual(reanalyze_reports(self.path, "2026-08-11", self.ai)["failed"], 1)
        after = self.snapshot(self.rid)
        self.assertEqual(after["status"], "ai_failed")
        for key in before.keys() - {"status", "updated_at"}:
            self.assertEqual(before[key], after[key], key)

    def test_invalid_selection_does_not_call_ai(self):
        """无匹配日期、商品对或不完整参数不调用 AI。"""
        for day, own, rival in [("2026-08-13", None, None), ("2026-08-11", "999", "888"),
                                ("2026-08-11", "10001", None), ("invalid", None, None)]:
            with self.assertRaises(ValueError):
                reanalyze_reports(self.path, day, self.ai, own, rival)
        self.ai.analyze.assert_not_called()
