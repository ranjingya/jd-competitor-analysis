"""测试基础报告重建的备份、保留字段和失败原子性。"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.database import Database
from app.jobs.rebuild import rebuild_reports
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository
from report_fixture import build_report_fixture
from test_dataset_repository import dataset_payload


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'data.db'
        self.db = Database(self.path)
        self.db.initialize()
        payload = dataset_payload()
        payload['report_date'] = '2026-08-17'
        did = DatasetRepository(self.db).store(payload)
        self.repo = ReportRepository(self.db)
        report = build_report_fixture()
        report['meta']['summary'] = '保留原 AI 摘要'
        self.rid = self.repo.upsert(did, report, status='ready')

    def test_preserves_ai_and_identity_with_backup(self):
        report = build_report_fixture()
        report['meta']['summary'] = '新基础摘要'
        with patch('app.jobs.rebuild.analyze_daily_dataset', return_value=report):
            result = rebuild_reports(self.path)
        self.assertEqual(result['updated']['day'], 1)
        self.assertTrue(Path(result['backup']).is_file())
        record = self.repo.get_record(self.rid)
        self.assertEqual(record['status'], 'ready')
        self.assertEqual(record['report']['meta']['summary'], '保留原 AI 摘要')
        with sqlite3.connect(result['backup']) as con:
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_calculation_failure_does_not_write(self):
        old = self.repo.get_record(self.rid)
        with patch('app.jobs.rebuild.analyze_daily_dataset', side_effect=ValueError('测试失败')):
            with self.assertRaises(ValueError):
                rebuild_reports(self.path)
        self.assertEqual(self.repo.get_record(self.rid), old)

    def test_missing_database_is_not_created(self):
        missing = self.path.parent / 'missing.db'
        with self.assertRaises(FileNotFoundError):
            rebuild_reports(missing)
        self.assertFalse(missing.exists())
