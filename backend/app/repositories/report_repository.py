"""持久化并读取 Web 看板报告。"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from ..database import Database, utc_now_text


LOGGER = logging.getLogger(__name__)
REPORT_STATUSES = {"pending_ai", "ready", "ai_failed"}
GRANULARITIES = {"day", "week", "month"}


class ReportRepository:
    """保存报告并提供按 ID 与周期的数据库查询。"""

    def __init__(self, database: Database | Path) -> None:
        """保存统一数据库实例。

        参数 database：统一数据库实例或兼容测试使用的数据库路径。
        """

        self.database = database if isinstance(database, Database) else Database(database)

    def initialize(self) -> None:
        """初始化统一数据库。"""

        self.database.initialize()

    def upsert(
        self,
        dataset_id: str | None,
        report: dict[str, Any],
        status: str = "pending_ai",
        report_id: str | None = None,
    ) -> str:
        """创建或更新一个业务周期的报告。

        功能说明：同一粒度、日期范围和商品对只保留一份报告；日报关联日数据集，周报和月报不绑定单个数据集。
        参数 dataset_id：数仓日报所属标准化数据集 ID；独立历史报告使用空值。
        参数 report：可由 Web 直接消费的完整报告对象。
        参数 status：`pending_ai`、`ready` 或 `ai_failed`。
        参数 report_id：可选报告 ID；新建且为空时生成 UUID。
        返回值：新建或已存在的报告 ID。
        """

        if status not in REPORT_STATUSES:
            raise ValueError(f"报告状态无效：{status}")
        selected_report_id = report_id or str(uuid.uuid4())
        report_json = json.dumps(report, ensure_ascii=False, sort_keys=True)
        now = utc_now_text()
        with self.database.connection() as connection:
            granularity, start_date, end_date, self_spu, competitor_spu = self._resolve_scope(
                connection,
                dataset_id,
                report,
            )
            existing = connection.execute(
                """
                SELECT report_id, dataset_id, status
                FROM reports
                WHERE granularity = ? AND start_date = ? AND end_date = ?
                  AND self_spu = ? AND competitor_spu = ?
                """,
                (granularity, start_date, end_date, self_spu, competitor_spu),
            ).fetchone()
            if existing is not None:
                if (
                    existing["dataset_id"] == dataset_id
                    and status == "pending_ai"
                    and existing["status"] in {"ready", "ai_failed"}
                ):
                    LOGGER.info(
                        "相同数据集报告已处于 AI 终态，保留现有内容：report_id=%s，status=%s",
                        existing["report_id"],
                        existing["status"],
                    )
                    return str(existing["report_id"])
                connection.execute(
                    """
                    UPDATE reports
                    SET dataset_id = ?, status = ?, report_json = ?, updated_at = ?
                    WHERE report_id = ?
                    """,
                    (dataset_id, status, report_json, now, existing["report_id"]),
                )
                LOGGER.info("报告已更新：report_id=%s，status=%s", existing["report_id"], status)
                return str(existing["report_id"])
            try:
                connection.execute(
                    """
                    INSERT INTO reports (
                        report_id, dataset_id, granularity, start_date, end_date,
                        self_spu, competitor_spu,
                        status, report_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        selected_report_id,
                        dataset_id,
                        granularity,
                        start_date,
                        end_date,
                        self_spu,
                        competitor_spu,
                        status,
                        report_json,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                LOGGER.exception("报告写入失败：dataset_id=%s", dataset_id)
                raise
        LOGGER.info("报告已创建：report_id=%s，status=%s", selected_report_id, status)
        return selected_report_id

    @staticmethod
    def _resolve_scope(
        connection: sqlite3.Connection,
        dataset_id: str | None,
        report: dict[str, Any],
    ) -> tuple[str, str, str, str, str]:
        """解析报告粒度、日期范围和商品对。"""

        if dataset_id is not None:
            dataset = connection.execute(
                """
                SELECT report_date, self_spu, competitor_spu
                FROM analysis_datasets
                WHERE dataset_id = ?
                """,
                (dataset_id,),
            ).fetchone()
            if dataset is None:
                raise FileNotFoundError(dataset_id)
            report_date = str(dataset["report_date"])
            return (
                "day",
                report_date,
                report_date,
                str(dataset["self_spu"]),
                str(dataset["competitor_spu"]),
            )

        meta = report.get("meta")
        if not isinstance(meta, dict):
            raise ValueError("周报或月报缺少 meta")
        granularity = str(meta.get("granularity") or "")
        start_date = str(meta.get("period_start") or "")
        end_date = str(meta.get("period_end") or "")
        self_spu = str(meta.get("self_spu") or "")
        competitor_spu = str(meta.get("competitor_spu") or "")
        if granularity not in GRANULARITIES:
            raise ValueError(f"报告粒度无效：{granularity}")
        if not all((start_date, end_date, self_spu, competitor_spu)):
            raise ValueError("独立报告缺少日期范围或商品对")
        if granularity == "day" and start_date != end_date:
            raise ValueError("独立日报的开始日期和结束日期必须相同")
        return granularity, start_date, end_date, self_spu, competitor_spu

    def activate_pending(
        self,
        report_id: str,
        dataset_id: str | None,
        report: dict[str, Any],
    ) -> None:
        """激活新 AI 输入对应的基础报告。

        功能说明：确认创建了新任务后，将唯一报告替换为当前数据集的基础内容并标记为 pending_ai。
        参数 report_id：需要更新的唯一报告 ID。
        参数 dataset_id：新任务使用的日数据集 ID；周报和月报使用空值。
        参数 report：尚未合并 AI 结果的基础报告。
        返回值：无。
        """

        now = utc_now_text()
        with self.database.connection() as connection:
            updated = connection.execute(
                """
                UPDATE reports
                SET dataset_id = ?, status = 'pending_ai', report_json = ?, updated_at = ?
                WHERE report_id = ?
                """,
                (
                    dataset_id,
                    json.dumps(report, ensure_ascii=False, sort_keys=True),
                    now,
                    report_id,
                ),
            )
        if updated.rowcount != 1:
            raise FileNotFoundError(report_id)
        LOGGER.info("报告已进入 AI 待处理状态：report_id=%s，dataset_id=%s", report_id, dataset_id)

    def get(self, report_id: str) -> dict[str, Any]:
        """按报告 ID 读取完整报告。

        参数 report_id：报告 ID。
        返回值：反序列化后的完整看板 JSON。
        """

        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT report_json FROM reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(report_id)
        return json.loads(row["report_json"])

    def get_record(self, report_id: str) -> dict[str, Any]:
        """读取报告索引字段和完整 JSON。"""

        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT r.*, d.quality_status
                FROM reports r
                LEFT JOIN analysis_datasets d ON d.dataset_id = r.dataset_id
                WHERE r.report_id = ?
                """,
                (report_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(report_id)
        return {
            "report_id": row["report_id"],
            "dataset_id": row["dataset_id"],
            "granularity": row["granularity"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "self_spu": row["self_spu"],
            "competitor_spu": row["competitor_spu"],
            "quality_status": row["quality_status"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "report": json.loads(row["report_json"]),
        }

    def get_skus(self, report_id: str) -> dict[str, Any]:
        """读取生成指定报告时使用的本品 SKU 构成。

        功能说明：日报读取直接关联的数据集快照；周报和月报合并来源日报的数据集快照，并按 SPU/SKU 去重。
        参数 report_id：报告 ID。
        返回值：包含周期、本品 SPU 和五字段 SKU 列表的对象。
        """

        with self.database.connection() as connection:
            report_row = connection.execute(
                "SELECT * FROM reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if report_row is None:
                raise FileNotFoundError(report_id)
            dataset_rows = []
            if report_row["dataset_id"] is not None:
                dataset_row = connection.execute(
                    "SELECT dataset_id, payload_json FROM analysis_datasets WHERE dataset_id = ?",
                    (report_row["dataset_id"],),
                ).fetchone()
                if dataset_row is not None:
                    dataset_rows.append(dataset_row)
            else:
                report = json.loads(report_row["report_json"])
                meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
                raw_source_report_ids = meta.get("source_report_ids", [])
                source_report_ids = (
                    [
                        str(item)
                        for item in raw_source_report_ids
                        if str(item).strip()
                    ]
                    if isinstance(raw_source_report_ids, list)
                    else []
                )
                if source_report_ids:
                    placeholders = ",".join("?" for _ in source_report_ids)
                    dataset_rows = connection.execute(
                        f"""
                        SELECT dataset.dataset_id, dataset.payload_json
                        FROM reports AS report
                        JOIN analysis_datasets AS dataset ON dataset.dataset_id = report.dataset_id
                        WHERE report.report_id IN ({placeholders})
                        ORDER BY report.start_date, report.report_id
                        """,
                        source_report_ids,
                    ).fetchall()

        components: dict[tuple[str, str], dict[str, Any]] = {}
        source_dataset_ids: list[str] = []
        for dataset_row in dataset_rows:
            source_dataset_ids.append(str(dataset_row["dataset_id"]))
            payload = json.loads(dataset_row["payload_json"])
            raw_components = payload.get("self_product", {}).get("sku_components", [])
            for item in raw_components:
                if not isinstance(item, dict):
                    continue
                component = {
                    "spu_id": item.get("spu_id"),
                    "sku_id": item.get("sku_id"),
                    "barcode_69": item.get("barcode_69"),
                    "product_name": item.get("product_name"),
                    "specification": item.get("specification"),
                }
                key = (str(component["spu_id"] or ""), str(component["sku_id"] or ""))
                if all(key):
                    components[key] = component

        items = list(components.values())
        return {
            "report_id": str(report_row["report_id"]),
            "dataset_id": report_row["dataset_id"],
            "source_dataset_ids": source_dataset_ids,
            "granularity": str(report_row["granularity"]),
            "start_date": str(report_row["start_date"]),
            "end_date": str(report_row["end_date"]),
            "spu_id": str(report_row["self_spu"]),
            "sku_count": len(items),
            "items": items,
        }

    def read_index(self) -> dict[str, Any]:
        """生成与当前 Web 兼容的报告索引。

        功能说明：从数据库按更新时间倒序读取日、周、月报告，并按粒度分组。
        返回值：包含 day、week 和 month 数组的报告索引。
        """

        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT r.report_id, r.dataset_id, r.granularity, r.start_date, r.end_date,
                       r.self_spu, r.competitor_spu, r.status, r.report_json, r.updated_at,
                       d.quality_status
                FROM reports r
                LEFT JOIN analysis_datasets d ON d.dataset_id = r.dataset_id
                ORDER BY r.updated_at DESC, r.report_id
                """
            ).fetchall()
        grouped_entries: dict[str, list[dict[str, Any]]] = {
            "day": [],
            "week": [],
            "month": [],
        }
        for row in rows:
            report = json.loads(row["report_json"])
            meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
            self_product = (
                meta.get("self_product")
                if isinstance(meta.get("self_product"), dict)
                else {}
            )
            competitor_product = (
                meta.get("competitor_product")
                if isinstance(meta.get("competitor_product"), dict)
                else {}
            )
            granularity = str(row["granularity"])
            period_key = (
                f"day:{row['start_date']}"
                if granularity == "day"
                else f"{granularity}:{row['start_date']}:{row['end_date']}"
            )
            grouped_entries[granularity].append(
                {
                    "report_id": row["report_id"],
                    "dataset_id": row["dataset_id"],
                    "period": meta.get("period") or row["start_date"],
                    "period_key": period_key,
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "self_spu": row["self_spu"],
                    "competitor_spu": row["competitor_spu"],
                    "self_name": self_product.get("name") or meta.get("self_name"),
                    "self_image_url": self_product.get("image_url"),
                    "competitor_name": (
                        competitor_product.get("name") or meta.get("competitor_name")
                    ),
                    "competitor_image_url": competitor_product.get("image_url"),
                    "quality_status": row["quality_status"],
                    "status": row["status"],
                    "title": meta.get("title"),
                    "summary": meta.get("summary"),
                    "path": f"/api/reports/{row['report_id']}",
                    "updated_at": row["updated_at"],
                }
            )
        updated_at = max((str(row["updated_at"]) for row in rows), default=None)
        return {
            "schema_version": "2.0",
            "updated_at": updated_at,
            "meta": {},
            "reports": grouped_entries,
        }

    def read_report(
        self,
        granularity: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """按粒度和周期读取最新报告。

        功能说明：按粒度和起止日期返回最近更新的报告。
        参数 granularity：day、week 或 month。
        参数 start_date：周期开始日期。
        参数 end_date：周期结束日期。
        返回值：反序列化后的完整报告 JSON。
        """

        if granularity not in GRANULARITIES:
            raise ValueError(f"不支持的报告粒度：{granularity}")
        try:
            parsed_start = date.fromisoformat(start_date)
            parsed_end = date.fromisoformat(end_date)
        except ValueError as error:
            raise ValueError("报告日期格式必须为 YYYY-MM-DD") from error
        if parsed_start > parsed_end:
            raise ValueError("报告开始日期不能晚于结束日期")
        if granularity == "day" and start_date != end_date:
            raise ValueError("日报的 start_date 和 end_date 必须相同")
        if granularity in {"week", "month"} and start_date == end_date:
            raise ValueError("周报和月报必须提供完整日期范围")
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT report_json
                FROM reports
                WHERE granularity = ? AND start_date = ? AND end_date = ?
                ORDER BY updated_at DESC, report_id
                LIMIT 1
                """,
                (granularity, start_date, end_date),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"{granularity}:{start_date}:{end_date}")
        return json.loads(row["report_json"])
