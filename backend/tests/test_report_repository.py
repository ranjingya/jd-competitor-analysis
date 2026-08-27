"""测试数据库报告仓库。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository


class ReportRepositoryTest(unittest.TestCase):
    """验证报告写入、更新、索引和周期读取。"""

    def setUp(self) -> None:
        """创建统一数据库和一份标准化数据集。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "data.db"
        datasets = DatasetRepository(database_path)
        datasets.initialize()
        self.dataset_id = datasets.store(
            {
                "report_date": "2026-08-17",
                "pair": {
                    "self_spu": "10001",
                    "competitor_spu": "20001",
                },
                "self_product": {
                    "sku_components": [
                        {
                            "spu_id": "10001",
                            "sku_id": "30001",
                            "barcode_69": "69001",
                            "product_name": "测试商品",
                            "specification": "蓝色",
                        }
                    ]
                },
                "quality": {"status": "partial"},
            },
            dataset_id="dataset-1",
        )
        self.datasets = datasets
        self.repository = ReportRepository(database_path)

    def tearDown(self) -> None:
        """清理测试数据库。"""

        self.temporary_directory.cleanup()

    def test_empty_index_and_report_upsert(self) -> None:
        """空库返回稳定索引，同一数据集重复写入应更新原报告。"""

        self.assertEqual(self.repository.list_product_pairs()["items"], [])
        report_id = self.repository.upsert(
            self.dataset_id,
            {
                "meta": {
                    "title": "日报",
                    "summary": "基础报告",
                    "self_product": {"name": "本品名称"},
                    "competitor_product": {"name": "竞品名称"},
                }
            },
            report_id="report-1",
        )
        repeated_id = self.repository.upsert(
            self.dataset_id,
            {
                "meta": {
                    "title": "日报",
                    "summary": "AI 已完成",
                    "self_product": {
                        "name": "本品名称",
                        "image_url": "https://example.com/self.jpg",
                    },
                    "competitor_product": {
                        "name": "竞品名称",
                        "image_url": "https://example.com/competitor.jpg",
                    },
                }
            },
            status="ready",
            report_id="report-other",
        )
        terminal_id = self.repository.upsert(
            self.dataset_id,
            {"meta": {"title": "日报", "summary": "重复生成的基础报告"}},
            status="pending_ai",
        )

        self.assertEqual(report_id, "report-1")
        self.assertEqual(repeated_id, "report-1")
        self.assertEqual(terminal_id, "report-1")
        self.assertEqual(self.repository.get("report-1")["meta"]["summary"], "AI 已完成")
        entry = self.repository.list_product_pairs()["items"][0]["latest_reports"]["day"]
        self.assertEqual(entry["path"], "/api/reports/report-1")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(entry["quality_status"], "partial")
        self.assertEqual(entry["self_name"], "本品名称")
        self.assertEqual(entry["competitor_name"], "竞品名称")
        self.assertEqual(entry["self_image_url"], "https://example.com/self.jpg")
        self.assertEqual(entry["competitor_image_url"], "https://example.com/competitor.jpg")

    def test_day_lookup_and_invalid_path(self) -> None:
        """日报可按起止日期读取，无效日期应被拒绝。"""

        self.repository.upsert(self.dataset_id, {"meta": {"title": "日报"}}, report_id="report-1")

        self.assertEqual(
            self.repository.read_report("day", "2026-08-17", "2026-08-17")["meta"]["title"],
            "日报",
        )
        with self.assertRaisesRegex(ValueError, "日期格式"):
            self.repository.read_report("day", "../../.env", "2026-08-17")
        with self.assertRaisesRegex(ValueError, "必须相同"):
            self.repository.read_report("day", "2026-08-17", "2026-08-18")

    def test_ready_day_report_lookup_uses_exact_business_key(self) -> None:
        """补洞查询只应命中日期、商品对和状态均一致的完整日报。"""

        self.repository.upsert(
            self.dataset_id,
            {"meta": {"title": "日报"}},
            status="ready",
            report_id="report-1",
        )

        self.assertEqual(
            self.repository.find_ready_day_report("2026-08-17", "10001", "20001"),
            {"report_id": "report-1", "dataset_id": self.dataset_id},
        )
        self.assertIsNone(
            self.repository.find_ready_day_report("2026-08-16", "10001", "20001")
        )
        self.assertIsNone(
            self.repository.find_ready_day_report("2026-08-17", "10001", "99999")
        )

    def test_product_pairs_periods_and_trends_are_lightweight(self) -> None:
        """首次导航、周期选择和趋势查询应返回各自需要的轻量数据。"""

        previous_dataset_id = self.datasets.store(
            {
                "report_date": "2026-08-16",
                "pair": {
                    "self_spu": "10001",
                    "competitor_spu": "20001",
                },
                "quality": {"status": "ready"},
            },
            dataset_id="dataset-previous",
        )
        for dataset_id, report_id, report_date, self_gmv, competitor_gmv in (
            (previous_dataset_id, "report-previous", "2026-08-16", 100.0, 80.0),
            (self.dataset_id, "report-latest", "2026-08-17", 120.0, 90.0),
        ):
            self.repository.upsert(
                dataset_id,
                {
                    "meta": {
                        "title": "日报",
                        "period_start": report_date,
                        "period_end": report_date,
                        "self_product": {"name": "本品名称"},
                        "competitor_product": {"name": "竞品名称"},
                    },
                    "comparison": [
                        {
                            "metric_id": "gmv",
                            "self_value": self_gmv,
                            "competitor_value": competitor_gmv,
                        }
                    ],
                },
                status="ready",
                report_id=report_id,
            )

        pairs = self.repository.list_product_pairs()
        periods = self.repository.list_periods(
            "10001", "20001", "day", "2026-08"
        )
        trends = self.repository.read_trends(
            "10001", "20001", "day", "2026-08-16", "2026-08-17"
        )

        self.assertEqual(len(pairs["items"]), 1)
        self.assertEqual(
            pairs["items"][0]["latest_reports"]["day"]["report_id"],
            "report-latest",
        )
        self.assertEqual(pairs["items"][0]["report_counts"]["day"], 2)
        self.assertEqual(periods["contexts"], ["2026-08"])
        self.assertEqual(periods["report_count"], 2)
        self.assertEqual(
            [entry["report_id"] for entry in periods["items"]],
            ["report-previous", "report-latest"],
        )
        self.assertEqual(len(trends["items"]), 2)
        self.assertEqual(trends["items"][0]["core_metrics"][0]["self_value"], 100.0)
        self.assertNotIn("traffic_sources", trends["items"][0])

    def test_product_images_are_synced_to_existing_reports(self) -> None:
        """外部主图配置应按 SPU 更新已有报告的两侧主图字段。"""

        self.repository.upsert(
            self.dataset_id,
            {
                "meta": {
                    "title": "日报",
                    "self_product": {
                        "name": "本品名称",
                        "image_url": "https://example.com/old-self.jpg",
                    },
                    "competitor_product": {
                        "name": "竞品名称",
                        "image_url": "https://example.com/old-competitor.jpg",
                    },
                }
            },
            report_id="report-1",
        )

        result = self.repository.sync_product_images(
            {
                "10001": {"name": "本品名称", "image_url": "https://example.com/new-self.jpg"},
                "20001": {
                    "name": "竞品名称",
                    "image_url": "https://example.com/new-competitor.jpg",
                },
                "30001": {"name": "未使用商品", "image_url": None},
            }
        )
        entry = self.repository.list_product_pairs()["items"][0]["latest_reports"]["day"]

        self.assertEqual(result["products"], 3)
        self.assertEqual(result["self_reports"], 1)
        self.assertEqual(result["competitor_reports"], 1)
        self.assertEqual(result["updated_fields"], 2)
        self.assertEqual(entry["self_image_url"], "https://example.com/new-self.jpg")
        self.assertEqual(
            entry["competitor_image_url"],
            "https://example.com/new-competitor.jpg",
        )

    def test_report_skus_come_from_dataset_snapshot(self) -> None:
        """日报 SKU 接口数据应来自生成报告时的数据集快照。"""

        self.repository.upsert(self.dataset_id, {"meta": {"title": "日报"}}, report_id="report-1")

        result = self.repository.get_skus("report-1")

        self.assertEqual(result["spu_id"], "10001")
        self.assertEqual(result["sku_count"], 1)
        self.assertEqual(
            result["items"][0],
            {
                "spu_id": "10001",
                "sku_id": "30001",
                "barcode_69": "69001",
                "product_name": "测试商品",
                "specification": "蓝色",
            },
        )

    def test_new_dataset_version_updates_same_business_report(self) -> None:
        """同一日期商品对的新数据版本应更新原报告，不新增第二份报告。"""

        report_id = self.repository.upsert(
            self.dataset_id,
            {"meta": {"title": "旧版本"}},
            status="ready",
            report_id="report-1",
        )
        new_dataset_id = self.datasets.store(
            {
                "report_date": "2026-08-17",
                "pair": {
                    "self_spu": "10001",
                    "competitor_spu": "20001",
                },
                "quality": {"status": "ready"},
                "revision": 2,
            },
            dataset_id="dataset-2",
        )

        updated_report_id = self.repository.upsert(
            new_dataset_id,
            {"meta": {"title": "新版本"}},
            report_id="report-2",
        )

        self.assertEqual(updated_report_id, report_id)
        self.assertEqual(self.repository.get_record(report_id)["dataset_id"], new_dataset_id)
        pair = self.repository.list_product_pairs()["items"][0]
        self.assertEqual(pair["latest_reports"]["day"]["status"], "pending_ai")
        self.assertEqual(pair["report_counts"]["day"], 1)

    def test_week_report_uses_period_without_dataset(self) -> None:
        """周报应按起止日期保存，且不绑定单个日数据集。"""

        self.repository.upsert(
            self.dataset_id,
            {"meta": {"title": "日报"}},
            report_id="report-day",
        )
        weekly_report = {
            "meta": {
                "title": "自然周报告",
                "granularity": "week",
                "period_start": "2026-08-17",
                "period_end": "2026-08-23",
                "self_spu": "10001",
                "competitor_spu": "20001",
                "source_report_ids": ["report-day"],
                "period_days": 7,
                "available_days": 6,
                "missing_days": ["2026-08-19"],
            },
            "quality_status": "partial",
        }

        report_id = self.repository.upsert(None, weekly_report, report_id="report-week")
        record = self.repository.get_record(report_id)
        weekly_entry = self.repository.list_product_pairs()["items"][0]["latest_reports"]["week"]

        self.assertIsNone(record["dataset_id"])
        self.assertEqual(record["granularity"], "week")
        self.assertEqual(record["start_date"], "2026-08-17")
        self.assertEqual(record["end_date"], "2026-08-23")
        self.assertEqual(weekly_entry["period_key"], "week:2026-08-17:2026-08-23")
        self.assertEqual(weekly_entry["period_days"], 7)
        self.assertEqual(weekly_entry["available_days"], 6)
        self.assertEqual(weekly_entry["missing_days"], ["2026-08-19"])
        self.assertEqual(record["report"]["quality_status"], "partial")
        self.assertEqual(record["report"]["report_status"], "pending_ai")
        self.assertEqual(
            self.repository.read_report("week", "2026-08-17", "2026-08-23")["meta"]["title"],
            "自然周报告",
        )
        self.assertEqual(self.repository.get_skus(report_id)["sku_count"], 1)


if __name__ == "__main__":
    unittest.main()
