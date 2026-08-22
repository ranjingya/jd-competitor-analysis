"""测试标准化日数据的内容去重和读取。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.repositories.dataset_repository import DatasetRepository, dataset_source_hash


def dataset_payload(gmv: int = 1000) -> dict[str, object]:
    """生成最小完整数据集测试对象。"""

    return {
        "schema_version": "2.0",
        "report_date": "2026-08-11",
        "pair": {
            "compare_number": "10001+20001",
            "self_spu": "10001",
            "competitor_spu": "20001",
        },
        "self_product": {"spu_daily_metrics": {"gmv": gmv}},
        "sources": {},
        "quality": {"status": "ready", "issues": []},
    }


class DatasetRepositoryTest(unittest.TestCase):
    """验证稳定哈希、重复复用和版本新增。"""

    def setUp(self) -> None:
        """创建独立 Backend 数据库。"""

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = DatasetRepository(Path(self.temporary_directory.name) / "data.db")
        self.repository.initialize()

    def tearDown(self) -> None:
        """清理测试数据库。"""

        self.temporary_directory.cleanup()

    def test_same_content_reuses_dataset_id(self) -> None:
        """相同内容即使字典顺序不同也应复用数据集。"""

        payload = dataset_payload()
        first_id = self.repository.store(payload, dataset_id="dataset-first")
        reordered = {key: payload[key] for key in reversed(payload)}
        second_id = self.repository.store(reordered, dataset_id="dataset-second")

        self.assertEqual(first_id, "dataset-first")
        self.assertEqual(second_id, "dataset-first")
        stored = self.repository.get(first_id)
        self.assertEqual(stored["payload"], payload)
        self.assertEqual(stored["source_hash"], dataset_source_hash(payload))

    def test_changed_content_creates_new_dataset_version(self) -> None:
        """同日期商品对的数据变化时应新增不可变版本。"""

        first_id = self.repository.store(dataset_payload(1000), dataset_id="dataset-v1")
        second_id = self.repository.store(dataset_payload(1200), dataset_id="dataset-v2")

        self.assertEqual(first_id, "dataset-v1")
        self.assertEqual(second_id, "dataset-v2")

    def test_invalid_pair_or_quality_is_rejected(self) -> None:
        """商品对和质量字段不一致时不得写入。"""

        payload = dataset_payload()
        pair = payload["pair"]
        assert isinstance(pair, dict)
        pair["compare_number"] = "wrong"
        with self.assertRaisesRegex(ValueError, "商品对字段不一致"):
            self.repository.store(payload)


if __name__ == "__main__":
    unittest.main()
