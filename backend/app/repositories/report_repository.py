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
    """保存报告并提供数据库查询与旧 API 兼容读取。"""

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
        dataset_id: str,
        report: dict[str, Any],
        status: str = "pending_ai",
        report_id: str | None = None,
    ) -> str:
        """创建或更新一个数据集的报告。

        功能说明：一个数据集只保留一份报告；重复计算时更新 JSON、状态和更新时间。
        参数 dataset_id：报告所属标准化数据集 ID。
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
            existing = connection.execute(
                "SELECT report_id, status FROM reports WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
            if existing is not None:
                if status == "pending_ai" and existing["status"] in {"ready", "ai_failed"}:
                    LOGGER.info(
                        "报告已处于 AI 终态，保留现有内容：report_id=%s，status=%s",
                        existing["report_id"],
                        existing["status"],
                    )
                    return str(existing["report_id"])
                connection.execute(
                    """
                    UPDATE reports
                    SET status = ?, report_json = ?, updated_at = ?
                    WHERE dataset_id = ?
                    """,
                    (status, report_json, now, dataset_id),
                )
                LOGGER.info("报告已更新：report_id=%s，status=%s", existing["report_id"], status)
                return str(existing["report_id"])
            try:
                connection.execute(
                    """
                    INSERT INTO reports (
                        report_id, dataset_id, status, report_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (selected_report_id, dataset_id, status, report_json, now, now),
                )
            except sqlite3.IntegrityError:
                LOGGER.exception("报告写入失败：dataset_id=%s", dataset_id)
                raise
        LOGGER.info("报告已创建：report_id=%s，status=%s", selected_report_id, status)
        return selected_report_id

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
                SELECT r.*, d.report_date, d.self_spu, d.competitor_spu, d.quality_status
                FROM reports r
                JOIN analysis_datasets d ON d.dataset_id = r.dataset_id
                WHERE r.report_id = ?
                """,
                (report_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(report_id)
        return {
            "report_id": row["report_id"],
            "dataset_id": row["dataset_id"],
            "report_date": row["report_date"],
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

        功能说明：从数据库按更新时间倒序读取日报，周报和月报在 MVP 阶段返回空数组。
        返回值：包含 day、week 和 month 数组的报告索引。
        """

        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT r.report_id, r.dataset_id, r.status, r.report_json, r.updated_at,
                       d.report_date, d.self_spu, d.competitor_spu, d.quality_status
                FROM reports r
                JOIN analysis_datasets d ON d.dataset_id = r.dataset_id
                ORDER BY r.updated_at DESC, r.report_id
                """
            ).fetchall()
        entries = []
        for row in rows:
            report = json.loads(row["report_json"])
            meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
            entries.append(
                {
                    "report_id": row["report_id"],
                    "dataset_id": row["dataset_id"],
                    "period": row["report_date"],
                    "period_key": f"day:{row['report_date']}",
                    "self_spu": row["self_spu"],
                    "competitor_spu": row["competitor_spu"],
                    "quality_status": row["quality_status"],
                    "status": row["status"],
                    "title": meta.get("title"),
                    "confidence": meta.get("confidence"),
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
            "reports": {"day": entries, "month": [], "week": []},
        }

    def read_report(self, granularity: str, period_directory: str) -> dict[str, Any]:
        """兼容按粒度和周期读取最新报告。

        功能说明：日维度按业务日期返回最近更新的报告；周月数据在 MVP 阶段不存在。
        参数 granularity：day、week 或 month。
        参数 period_directory：日期或日期区间。
        返回值：反序列化后的完整报告 JSON。
        """

        if granularity not in GRANULARITIES:
            raise ValueError(f"不支持的报告粒度：{granularity}")
        if not PERIOD_DIRECTORY_PATTERN.fullmatch(period_directory):
            raise ValueError(f"报告周期目录格式无效：{period_directory}")
        if granularity != "day" or "_" in period_directory:
            raise FileNotFoundError(period_directory)
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT r.report_json
                FROM reports r
                JOIN analysis_datasets d ON d.dataset_id = r.dataset_id
                WHERE d.report_date = ?
                ORDER BY r.updated_at DESC, r.report_id
                LIMIT 1
                """,
                (period_directory,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(period_directory)
        return json.loads(row["report_json"])
