"""测试正式日数据分析入库编排。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.database import Database
from app.jobs.daily_analysis import (
    ALREADY_RUNNING_EXIT_CODE,
    DAILY_DATA_MISSING_EXIT_CODE,
    DailyWarehouseDataMissingError,
    _date_data_status,
    _selected_report_dates,
    process_daily_pair,
    process_daily_pairs,
    run_warehouse_daily_analysis,
)
from app.job_lock import acquire_job_lock
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.task_repository import TaskRepository
from jd_competitor_analysis.warehouse_daily import WarehousePairNoDataError
from jd_competitor_analysis.warehouse_sources import ProductPair
from report_fixture import build_report_fixture


def dataset_payload(status: str = "partial") -> dict[str, object]:
    """生成可写入数据库的最小标准化数据集。"""

    return {
        "report_date": "2026-08-18",
        "pair": {
            "self_spu": "10001",
            "competitor_spu": "20001",
        },
        "self_product": {
            "sku_components": [],
            "quality": {"status": "partial"},
        },
        "sources": {},
        "quality": {"status": status, "issues": []},
    }


def report_payload() -> dict[str, object]:
    """读取可通过最终报告契约校验的基础报告。"""

    return build_report_fixture("2026-08-18")


def ai_analyzer() -> Mock:
    """创建返回有效 AI 结构的测试分析器。"""

    analyzer = Mock()
    analyzer.model = "deepseek-v4-pro"
    analyzer.analysis_version = "1.0"
    analyzer.prompt_hash = "prompt-hash"
    analyzer.analyze.return_value = {
        "summary": {
            "advantage": {"brief": "流量规模领先", "detail": ["本品流量规模领先。"]},
            "weakness": {"brief": "转化效率落后", "detail": ["本品转化效率落后。"]},
        },
        "findings": [],
        "recommendations": [],
    }
    return analyzer


class DailyAnalysisJobTest(unittest.TestCase):
    """验证单商品对写入和批量跳过规则。"""

    def setUp(self) -> None:
        """创建统一测试数据库和仓库。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temporary_directory.name) / "data.db")
        self.database.initialize()
        self.datasets = DatasetRepository(self.database)
        self.reports = ReportRepository(self.database)
        self.tasks = TaskRepository(self.database)
        self.pair = ProductPair("10001", "20001")

    def tearDown(self) -> None:
        """清理测试数据库。"""

        self.temporary_directory.cleanup()

    @patch("app.jobs.daily_analysis.build_ai_task_payload")
    @patch("app.jobs.daily_analysis.analyze_daily_dataset")
    @patch("app.jobs.daily_analysis.build_daily_dataset")
    def test_pair_writes_dataset_report_and_task(
        self,
        build_dataset: Mock,
        analyze_dataset: Mock,
        build_task_payload: Mock,
    ) -> None:
        """有效数据应依次写入数据集、报告和 AI 执行记录。"""

        build_dataset.return_value = dataset_payload()
        analyze_dataset.return_value = report_payload()
        build_task_payload.return_value = {"facts": {"metric": 1}}
        analyzer = ai_analyzer()

        result = process_daily_pair(
            Mock(),
            Mock(),
            self.pair,
            "2026-08-18",
            self.datasets,
            self.reports,
            self.tasks,
            analyzer,
            product_images={},
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(
            self.tasks.list_recent("completed", 20)[0]["report_id"],
            result["report_id"],
        )
        self.assertEqual(self.reports.get_record(result["report_id"])["dataset_id"], result["dataset_id"])

    @patch("app.jobs.daily_analysis.build_ai_task_payload")
    @patch("app.jobs.daily_analysis.analyze_daily_dataset")
    @patch("app.jobs.daily_analysis.build_daily_dataset")
    def test_new_pair_version_reuses_report_and_expires_old_task(
        self,
        build_dataset: Mock,
        analyze_dataset: Mock,
        build_task_payload: Mock,
    ) -> None:
        """同一日期商品对的新版本应复用报告，并只保留一个当前任务。"""

        first_dataset = dataset_payload()
        second_dataset = dataset_payload()
        second_dataset["revision"] = 2
        build_dataset.side_effect = [first_dataset, second_dataset]
        analyze_dataset.side_effect = [report_payload(), report_payload()]
        build_task_payload.side_effect = [
            {"facts": {"version": 1}},
            {"facts": {"version": 2}},
        ]

        first = process_daily_pair(
            Mock(),
            Mock(),
            self.pair,
            "2026-08-18",
            self.datasets,
            self.reports,
            self.tasks,
            ai_analyzer(),
            product_images={},
        )
        second = process_daily_pair(
            Mock(),
            Mock(),
            self.pair,
            "2026-08-18",
            self.datasets,
            self.reports,
            self.tasks,
            ai_analyzer(),
            product_images={},
        )

        self.assertEqual(first["report_id"], second["report_id"])
        self.assertNotEqual(first["dataset_id"], second["dataset_id"])
        self.assertEqual(
            self.tasks.list_recent("expired", 20)[0]["analysis_id"],
            first["analysis_id"],
        )
        self.assertEqual(
            self.tasks.list_recent("completed", 20)[0]["analysis_id"],
            second["analysis_id"],
        )
        self.assertEqual(
            self.reports.get_record(second["report_id"])["dataset_id"],
            second["dataset_id"],
        )
        self.assertEqual(
            self.reports.list_product_pairs()["items"][0]["report_counts"]["day"],
            1,
        )

    @patch("app.jobs.daily_analysis.analyze_daily_dataset")
    @patch("app.jobs.daily_analysis.build_daily_dataset")
    def test_invalid_dataset_is_stored_without_report_or_task(
        self,
        build_dataset: Mock,
        analyze_dataset: Mock,
    ) -> None:
        """本品或核心事实无效时只保留数据集用于排查。"""

        build_dataset.return_value = dataset_payload("invalid")

        result = process_daily_pair(
            Mock(),
            Mock(),
            self.pair,
            "2026-08-18",
            self.datasets,
            self.reports,
            self.tasks,
            ai_analyzer(),
        )

        self.assertEqual(result["status"], "invalid")
        self.assertIsNone(result["report_id"])
        self.assertEqual(self.tasks.list_recent(), [])
        analyze_dataset.assert_not_called()

    @patch("app.jobs.daily_analysis.process_daily_pair")
    def test_pair_without_data_is_skipped_without_stopping_batch(self, process_pair: Mock) -> None:
        """完全没有数仓记录的商品对应跳过并继续下一组。"""

        process_pair.side_effect = [
            WarehousePairNoDataError(
                "2026-08-18",
                self.pair,
            ),
            {
                "self_spu": "10002",
                "competitor_spu": "20002",
                "status": "ready",
                "quality_status": "ready",
                "dataset_id": "dataset-2",
                "report_id": "report-2",
                "analysis_id": "task-2",
            },
        ]
        results = process_daily_pairs(
            Mock(),
            Mock(),
            [self.pair, ProductPair("10002", "20002")],
            "2026-08-18",
            self.database,
            ai_analyzer(),
        )

        self.assertEqual(
            [item["status"] for item in results],
            ["no_data", "ready"],
        )
        self.assertEqual(process_pair.call_count, 2)

    def test_date_is_missing_only_when_every_pair_has_no_data(self) -> None:
        """单个商品对无数据正常，全部商品对无数据才是整日异常。"""

        mixed = _date_data_status(
            "2026-08-18",
            [{"status": "no_data"}, {"status": "ready"}],
            2,
        )
        missing = _date_data_status(
            "2026-08-18",
            [{"status": "no_data"}, {"status": "no_data"}],
            2,
        )
        selected_missing = _date_data_status(
            "2026-08-18",
            [{"status": "no_data"}],
            1,
            covers_all_pairs=False,
        )

        self.assertEqual(mixed["status"], "available")
        self.assertEqual(mixed["no_data_pairs"], 1)
        self.assertEqual(missing["status"], "data_missing")
        self.assertEqual(missing["no_data_pairs"], 2)
        self.assertEqual(selected_missing["status"], "selection_no_data")
        self.assertEqual(
            DailyWarehouseDataMissingError("2026-08-18").code,
            DAILY_DATA_MISSING_EXIT_CODE,
        )

    @patch("app.jobs.daily_analysis.random.uniform", return_value=0)
    @patch("app.jobs.daily_analysis.time.sleep")
    @patch("app.jobs.daily_analysis.process_daily_pair")
    def test_warehouse_concurrency_retries_three_times(
        self,
        process_pair: Mock,
        sleep: Mock,
        _random: Mock,
    ) -> None:
        """数仓并发达到上限时应按固定间隔定向重试并隐藏完整 SQL。"""

        process_pair.side_effect = RuntimeError(
            "Exceed concurrency limit: 3 backend [id=10004]\n[SQL: SELECT * FROM secret_table]"
        )

        with self.assertLogs("app.jobs.daily_analysis", level="ERROR") as captured:
            results = process_daily_pairs(
                Mock(),
                Mock(),
                [self.pair],
                "2026-08-18",
                self.database,
                ai_analyzer(),
            )

        self.assertEqual(results[0]["message"], "数仓查询并发已达到上限 3，请稍后重试")
        self.assertEqual(results[0]["status"], "concurrency_exhausted")
        self.assertFalse(results[0]["retryable"])
        self.assertEqual(results[0]["attempt"], 4)
        self.assertNotIn("SELECT", results[0]["message"])
        self.assertEqual(process_pair.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60, 120])
        self.assertIn("商品对处理失败（数仓并发）", captured.output[0])

    @patch("app.jobs.daily_analysis.random.uniform", return_value=0)
    @patch("app.jobs.daily_analysis.time.sleep")
    @patch("app.jobs.daily_analysis.process_daily_pair")
    def test_only_concurrency_pair_is_retried(
        self,
        process_pair: Mock,
        sleep: Mock,
        _random: Mock,
    ) -> None:
        """定向重试只处理触发数仓并发上限的商品对。"""

        successful = ProductPair("10002", "20002")
        process_pair.side_effect = [
            RuntimeError("Exceed concurrency limit: 3"),
            {
                "self_spu": successful.self_spu,
                "competitor_spu": successful.competitor_spu,
                "status": "ready",
            },
            {
                "self_spu": self.pair.self_spu,
                "competitor_spu": self.pair.competitor_spu,
                "status": "ready",
            },
        ]

        results = process_daily_pairs(
            Mock(),
            Mock(),
            [self.pair, successful],
            "2026-08-18",
            self.database,
            ai_analyzer(),
        )

        self.assertEqual([item["status"] for item in results], ["ready", "ready"])
        self.assertEqual([item["attempt"] for item in results], [2, 1])
        sleep.assert_called_once_with(30)
        self.assertEqual(process_pair.call_count, 3)

    @patch("app.jobs.daily_analysis.process_daily_pair")
    def test_pair_progress_callback_marks_start_and_completion(
        self,
        process_pair: Mock,
    ) -> None:
        """批处理应在商品对开始和最终结束时更新运行进度。"""

        process_pair.return_value = {
            "self_spu": self.pair.self_spu,
            "competitor_spu": self.pair.competitor_spu,
            "status": "ready",
        }
        events: list[tuple[str, ProductPair]] = []

        process_daily_pairs(
            Mock(),
            Mock(),
            [self.pair],
            "2026-08-18",
            self.database,
            ai_analyzer(),
            progress_callback=lambda stage, pair: events.append((stage, pair)),
        )

        self.assertEqual([stage for stage, _ in events], ["pair_started", "pair_completed"])

    @patch("app.jobs.daily_analysis.get_settings")
    def test_existing_process_lock_returns_dedicated_exit_code(
        self,
        get_settings: Mock,
    ) -> None:
        """已有任务持锁时应返回专用失败码而不是误报成功。"""

        lock_path = Path(self.temporary_directory.name) / "daily.lock"
        status_path = Path(self.temporary_directory.name) / "status.json"
        get_settings.return_value = SimpleNamespace(
            analysis_lock_path=lock_path,
            analysis_status_path=status_path,
            database_path=self.database.path,
        )
        args = SimpleNamespace(
            date="2026-08-18",
            yesterday=False,
        )

        with acquire_job_lock(lock_path):
            with self.assertRaises(SystemExit) as captured:
                run_warehouse_daily_analysis(args)

        self.assertEqual(captured.exception.code, ALREADY_RUNNING_EXIT_CODE)
        self.assertFalse(status_path.exists())

    def test_yesterday_mode_selects_recent_seven_days(self) -> None:
        """定时模式应由近到远检查昨天起最近七天。"""

        selected = _selected_report_dates(
            SimpleNamespace(yesterday=True),
            date(2026, 8, 24).isoformat(),
        )

        self.assertEqual(
            selected,
            [
                "2026-08-24",
                "2026-08-23",
                "2026-08-22",
                "2026-08-21",
                "2026-08-20",
                "2026-08-19",
                "2026-08-18",
            ],
        )
        self.assertEqual(
            _selected_report_dates(SimpleNamespace(yesterday=False), "2026-08-24"),
            ["2026-08-24"],
        )


if __name__ == "__main__":
    unittest.main()
