"""按业务模块持久化标准化日数据。"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..database import Database, utc_now_text


LOGGER = logging.getLogger(__name__)
QUALITY_STATUSES = {"ready", "partial", "invalid"}
SOURCE_COLUMNS = {
    "core_metrics": "core_metrics_json",
    "traffic_sources": "traffic_sources_json",
    "traffic_keywords": "traffic_keywords_json",
    "customer_profiles": "customer_profile_json",
    "promotion": "promotion_json",
}
DATASET_TOP_LEVEL_FIELDS = {
    "schema_version",
    "report_date",
    "pair",
    "self_product",
    "sources",
    "quality",
}


def canonical_json(data: dict[str, Any]) -> str:
    """生成用于存储和哈希的稳定 JSON 文本。"""

    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dataset_source_hash(payload: dict[str, Any]) -> str:
    """计算完整标准化日数据的 SHA-256。"""

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class DatasetRepository:
    """保存和读取不可变的标准化日数据版本。"""

    def __init__(self, database: Database | Path) -> None:
        """保存统一数据库实例。

        参数 database：统一数据库实例或兼容测试使用的数据库路径。
        """

        self.database = database if isinstance(database, Database) else Database(database)

    def initialize(self) -> None:
        """初始化统一数据库。"""

        self.database.initialize()

    def store(self, payload: dict[str, Any], dataset_id: str | None = None) -> str:
        """写入或复用一份标准化日数据。

        功能说明：校验日期、商品对和质量字段，按稳定内容哈希避免重复写入。
        参数 payload：符合标准化日数据契约的完整事实对象。
        参数 dataset_id：可选数据集 ID；为空时生成 UUID。
        返回值：新建或已存在的数据集 ID。
        """

        report_date = str(payload.get("report_date") or "")
        pair = payload.get("pair")
        quality = payload.get("quality")
        if not report_date or not isinstance(pair, dict) or not isinstance(quality, dict):
            raise ValueError("标准化日数据缺少 report_date、pair 或 quality")
        self_spu = str(pair.get("self_spu") or "")
        competitor_spu = str(pair.get("competitor_spu") or "")
        if not self_spu or not competitor_spu or self_spu == competitor_spu:
            raise ValueError("标准化日数据商品对字段无效")
        quality_status = str(quality.get("status") or "")
        if quality_status not in QUALITY_STATUSES:
            raise ValueError(f"标准化日数据质量状态无效：{quality_status}")

        source_hash = dataset_source_hash(payload)
        sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
        present_sources = [source_id for source_id in SOURCE_COLUMNS if source_id in sources]
        source_status = {
            "schema_version": payload.get("schema_version"),
            "quality": quality,
            "self_product_present": "self_product" in payload,
            "sources_present": "sources" in payload,
            "present_sources": present_sources,
            "extra": {
                key: value
                for key, value in payload.items()
                if key not in DATASET_TOP_LEVEL_FIELDS
            },
        }
        module_values = {
            column: canonical_json(sources.get(source_id, {}))
            for source_id, column in SOURCE_COLUMNS.items()
        }
        selected_dataset_id = dataset_id or str(uuid.uuid4())
        with self.database.connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO analysis_datasets (
                        dataset_id, report_date, self_spu, competitor_spu,
                        self_product_json, core_metrics_json, traffic_sources_json,
                        traffic_keywords_json, customer_profile_json, promotion_json,
                        source_status_json, quality_status, source_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        selected_dataset_id,
                        report_date,
                        self_spu,
                        competitor_spu,
                        canonical_json(payload.get("self_product", {})),
                        module_values["core_metrics_json"],
                        module_values["traffic_sources_json"],
                        module_values["traffic_keywords_json"],
                        module_values["customer_profile_json"],
                        module_values["promotion_json"],
                        canonical_json(source_status),
                        quality_status,
                        source_hash,
                        utc_now_text(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                existing = connection.execute(
                    "SELECT dataset_id FROM analysis_datasets WHERE source_hash = ?",
                    (source_hash,),
                ).fetchone()
                if existing is None:
                    raise error
                LOGGER.debug("相同内容的数据集已存在：dataset_id=%s", existing["dataset_id"])
                return str(existing["dataset_id"])
        LOGGER.debug("标准化数据集已写入：dataset_id=%s，date=%s", selected_dataset_id, report_date)
        return selected_dataset_id

    def get(self, dataset_id: str) -> dict[str, Any]:
        """读取一份标准化日数据。

        功能说明：从独立模块字段恢复下游确定性分析使用的标准化事实对象。
        参数 dataset_id：数据集 ID。
        返回值：包含索引字段和反序列化 payload 的数据集对象。
        """

        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_datasets WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(dataset_id)
        source_status = json.loads(row["source_status_json"])
        payload = dict(source_status.get("extra") or {})
        schema_version = source_status.get("schema_version")
        if schema_version is not None:
            payload["schema_version"] = schema_version
        payload.update(
            {
                "report_date": row["report_date"],
                "pair": {
                    "self_spu": row["self_spu"],
                    "competitor_spu": row["competitor_spu"],
                },
            }
        )
        if source_status.get("self_product_present"):
            payload["self_product"] = json.loads(row["self_product_json"])
        present_sources = set(source_status.get("present_sources") or [])
        if source_status.get("sources_present"):
            payload["sources"] = {
                source_id: json.loads(row[column])
                for source_id, column in SOURCE_COLUMNS.items()
                if source_id in present_sources
            }
        payload["quality"] = source_status.get("quality") or {
            "status": row["quality_status"]
        }
        return {
            "dataset_id": row["dataset_id"],
            "report_date": row["report_date"],
            "self_spu": row["self_spu"],
            "competitor_spu": row["competitor_spu"],
            "source_hash": row["source_hash"],
            "quality_status": row["quality_status"],
            "created_at": row["created_at"],
            "payload": payload,
        }
