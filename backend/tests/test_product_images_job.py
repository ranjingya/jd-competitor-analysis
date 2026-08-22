"""测试外部商品主图配置同步流程。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.jobs.product_images import sync_product_images
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository


class ProductImagesJobTest(unittest.TestCase):
    """验证运行数据目录中的主图文件可以独立同步。"""

    def test_external_json_updates_existing_report(self) -> None:
        """手动维护的外部 JSON 应更新数据库中的报告主图。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            database = Database(data_dir / "data.db")
            datasets = DatasetRepository(database)
            datasets.initialize()
            dataset_id = datasets.store(
                {
                    "report_date": "2026-08-17",
                    "pair": {
                        "compare_number": "10001+20001",
                        "self_spu": "10001",
                        "competitor_spu": "20001",
                    },
                    "quality": {"status": "ready"},
                }
            )
            reports = ReportRepository(database)
            report_id = reports.upsert(dataset_id, {"meta": {"title": "日报"}})
            product_images_path = data_dir / "product-images.json"
            product_images_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "products": {
                            "10001": {
                                "name": "本品",
                                "image_url": "https://example.com/self.jpg",
                            },
                            "20001": {
                                "name": "竞品",
                                "image_url": "https://example.com/competitor.jpg",
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = sync_product_images(database, product_images_path)
            report = reports.get(report_id)

        self.assertEqual(result["updated_fields"], 2)
        self.assertEqual(report["meta"]["self_product"]["image_url"], "https://example.com/self.jpg")
        self.assertEqual(
            report["meta"]["competitor_product"]["image_url"],
            "https://example.com/competitor.jpg",
        )


if __name__ == "__main__":
    unittest.main()
