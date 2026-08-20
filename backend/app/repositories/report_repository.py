"""持久化并读取 Web 看板报告。"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..database import Database, utc_now_text


LOGGER = logging.getLogger(__name__)
REPORT_STATUSES = {"pending_ai", "ready", "ai_failed"}
GRANULARITIES = {"day", "week", "month"}
PERIOD_DIRECTORY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:_\d{4}-\d{2}-\d{2})?$")


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
        参数 dataset_id：日报所属标准化数据集 ID；周报和月报使用空值。
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
        if granularity not in {"week", "month"}:
            raise ValueError("未绑定日数据集的报告只能使用 week 或 month 粒度")
        if not all((start_date, end_date, self_spu, competitor_spu)):
            raise ValueError("周报或月报缺少日期范围或商品对")
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

    def read_report(self, granularity: str, period_directory: str) -> dict[str, Any]:
        """按粒度和周期读取最新报告。

        功能说明：按粒度和起止日期返回最近更新的报告。
        参数 granularity：day、week 或 month。
        参数 period_directory：日期或日期区间。
        返回值：反序列化后的完整报告 JSON。
        """

        if granularity not in GRANULARITIES:
            raise ValueError(f"不支持的报告粒度：{granularity}")
        if not PERIOD_DIRECTORY_PATTERN.fullmatch(period_directory):
            raise ValueError(f"报告周期目录格式无效：{period_directory}")
        if "_" in period_directory:
            start_date, end_date = period_directory.split("_", 1)
        else:
            start_date = end_date = period_directory
        if granularity == "day" and start_date != end_date:
            raise FileNotFoundError(period_directory)
        if granularity in {"week", "month"} and start_date == end_date:
            raise FileNotFoundError(period_directory)
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
            raise FileNotFoundError(period_directory)
        return json.loads(row["report_json"])
