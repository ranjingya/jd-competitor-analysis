"""持久化完整标准化日数据。"""

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
        compare_number = str(pair.get("compare_number") or "")
        if compare_number != f"{self_spu}+{competitor_spu}" or not self_spu or not competitor_spu:
            raise ValueError("标准化日数据商品对字段不一致")
        quality_status = str(quality.get("status") or "")
        if quality_status not in QUALITY_STATUSES:
            raise ValueError(f"标准化日数据质量状态无效：{quality_status}")

        payload_json = canonical_json(payload)
        source_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        selected_dataset_id = dataset_id or str(uuid.uuid4())
        with self.database.connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO analysis_datasets (
                        dataset_id, report_date, self_spu, competitor_spu,
                        compare_number, source_hash, payload_json, quality_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        selected_dataset_id,
                        report_date,
                        self_spu,
                        competitor_spu,
                        compare_number,
                        source_hash,
                        payload_json,
                        quality_status,
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
                LOGGER.info("相同内容的数据集已存在：dataset_id=%s", existing["dataset_id"])
                return str(existing["dataset_id"])
        LOGGER.info("标准化数据集已写入：dataset_id=%s，date=%s", selected_dataset_id, report_date)
        return selected_dataset_id

    def get(self, dataset_id: str) -> dict[str, Any]:
        """读取一份标准化日数据。

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
        return {
            "dataset_id": row["dataset_id"],
            "report_date": row["report_date"],
            "self_spu": row["self_spu"],
            "competitor_spu": row["competitor_spu"],
            "compare_number": row["compare_number"],
            "source_hash": row["source_hash"],
            "quality_status": row["quality_status"],
            "created_at": row["created_at"],
            "payload": json.loads(row["payload_json"]),
        }
