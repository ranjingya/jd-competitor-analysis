"""使用 SQLite 持久化 AI 分析任务。"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..database import Database
from ..report_merge import merge_ai_result


LOGGER = logging.getLogger(__name__)


class TaskConflictError(RuntimeError):
    """任务状态、租约或数据版本冲突。"""


def _utc_now() -> datetime:
    """返回带时区的当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    """把时间转换为稳定的 ISO 字符串。"""

    return value.isoformat(timespec="seconds")


class TaskRepository:
    """管理 AI 任务的创建、领取、完成与失败状态。"""

    def __init__(self, database: Database | Path) -> None:
        self.database = database if isinstance(database, Database) else Database(database)

    def initialize(self) -> None:
        """初始化统一数据库。

        功能说明：创建持久化目录、三张业务表和索引，已有数据库保持原数据不变。
        返回值：无。
        """

        self.database.initialize()

    def enqueue(
        self,
        dataset_id: str,
        source_hash: str,
        payload: dict[str, Any],
        analysis_id: str | None = None,
    ) -> str:
        """创建待分析任务。

        功能说明：把后端脚本生成的结构化事实保存为 pending 任务，供 Mac Codex 后续领取。
        参数 dataset_id：任务所属标准化数据集 ID。
        参数 source_hash：当前 AI 输入的稳定内容哈希。
        参数 payload：只包含分析所需事实的结构化输入。
        参数 analysis_id：可选任务 ID；为空时自动生成。
        返回值：创建后的任务 ID。
        """

        task_id = analysis_id or str(uuid.uuid4())
        now = _iso(_utc_now())
        with self.database.connection() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO analysis_tasks (
                        analysis_id, dataset_id, source_hash, payload_json,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        task_id,
                        dataset_id,
                        source_hash,
                        json.dumps(payload, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                existing = connection.execute(
                    "SELECT analysis_id, dataset_id FROM analysis_tasks WHERE source_hash = ?",
                    (source_hash,),
                ).fetchone()
                if existing is None:
                    raise error
                if existing["dataset_id"] != dataset_id:
                    raise TaskConflictError("相同 AI 输入哈希已关联其他数据集") from error
                LOGGER.info(
                    "相同数据版本的 AI 任务已存在：analysis_id=%s，source_hash=%s",
                    existing["analysis_id"],
                    source_hash,
                )
                return str(existing["analysis_id"])
        LOGGER.info("AI 分析任务已创建：analysis_id=%s", task_id)
        return task_id

    def claim(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        """原子领取一条待分析任务。

        功能说明：回收过期租约后按创建时间领取一条 pending 任务，并生成本次提交所需租约令牌。
        参数 worker_id：领取任务的 Codex Worker 标识。
        参数 lease_seconds：本次任务租约有效秒数。
        返回值：已领取任务；没有可用任务时返回 None。
        """

        now = _utc_now()
        now_text = _iso(now)
        lease_expires_at = _iso(now + timedelta(seconds=lease_seconds))
        lease_token = secrets.token_urlsafe(32)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE analysis_tasks
                SET status = 'pending', worker_id = NULL, lease_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE status = 'processing' AND lease_expires_at < ?
                """,
                (now_text, now_text),
            )
            row = connection.execute(
                """
                SELECT analysis_id, dataset_id, source_hash, payload_json
                FROM analysis_tasks
                WHERE status = 'pending'
                ORDER BY created_at, analysis_id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE analysis_tasks
                SET status = 'processing', worker_id = ?, lease_token = ?, lease_expires_at = ?,
                    attempt_count = attempt_count + 1, error_message = NULL, updated_at = ?
                WHERE analysis_id = ? AND status = 'pending'
                """,
                (worker_id, lease_token, lease_expires_at, now_text, row["analysis_id"]),
            )
            connection.commit()
            LOGGER.info("AI 分析任务已领取：analysis_id=%s，worker_id=%s", row["analysis_id"], worker_id)
            return {
                "analysis_id": row["analysis_id"],
                "dataset_id": row["dataset_id"],
                "source_hash": row["source_hash"],
                "payload": json.loads(row["payload_json"]),
                "lease_token": lease_token,
                "lease_expires_at": lease_expires_at,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete(
        self,
        analysis_id: str,
        source_hash: str,
        lease_token: str,
        result: dict[str, Any],
    ) -> None:
        """完成已领取任务。

        功能说明：校验任务版本和有效租约后，在同一事务中保存 AI 原始结果、合并基础报告并将报告标记为 ready；相同结果的重复提交视为成功。
        参数 analysis_id：待完成的任务 ID。
        参数 source_hash：领取任务时返回的数据版本哈希。
        参数 lease_token：领取任务时返回的租约令牌。
        参数 result：通过 API Schema 校验的 AI 分析结果。
        返回值：无。
        """

        result_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
        now_text = _iso(_utc_now())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM analysis_tasks WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(analysis_id)
            if row["status"] == "completed":
                if row["source_hash"] == source_hash and row["result_json"] == result_json:
                    self._merge_report(connection, row["dataset_id"], result, now_text)
                    connection.commit()
                    return
                raise TaskConflictError("任务已经完成，不能覆盖已有 AI 结果")
            self._validate_active_lease(row, source_hash, lease_token, now_text)
            self._merge_report(connection, row["dataset_id"], result, now_text)
            connection.execute(
                """
                UPDATE analysis_tasks
                SET status = 'completed', result_json = ?, lease_token = NULL,
                    lease_expires_at = NULL, error_message = NULL,
                    updated_at = ?, completed_at = ?
                WHERE analysis_id = ?
                """,
                (result_json, now_text, now_text, analysis_id),
            )
            connection.commit()
            LOGGER.info("AI 分析任务已完成：analysis_id=%s", analysis_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail(self, analysis_id: str, lease_token: str, error_message: str) -> None:
        """记录已领取任务失败。

        功能说明：校验当前租约后保存失败原因，并将对应基础报告标记为 ai_failed，避免不完整 AI 结果进入正式报告。
        参数 analysis_id：失败任务 ID。
        参数 lease_token：领取任务时返回的租约令牌。
        参数 error_message：本次分析失败的可排查原因。
        返回值：无。
        """

        now_text = _iso(_utc_now())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM analysis_tasks WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(analysis_id)
            self._validate_active_lease(row, row["source_hash"], lease_token, now_text)
            report_update = connection.execute(
                "UPDATE reports SET status = 'ai_failed', updated_at = ? WHERE dataset_id = ?",
                (now_text, row["dataset_id"]),
            )
            if report_update.rowcount != 1:
                raise TaskConflictError("任务所属基础报告不存在")
            connection.execute(
                """
                UPDATE analysis_tasks
                SET status = 'failed', error_message = ?, lease_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE analysis_id = ?
                """,
                (error_message, now_text, analysis_id),
            )
            connection.commit()
            LOGGER.warning("AI 分析任务执行失败：analysis_id=%s，error=%s", analysis_id, error_message)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _merge_report(
        connection: sqlite3.Connection,
        dataset_id: str,
        result: dict[str, Any],
        updated_at: str,
    ) -> None:
        """在当前事务中合并并更新任务所属报告。"""

        report_row = connection.execute(
            "SELECT report_json FROM reports WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()
        if report_row is None:
            raise TaskConflictError("任务所属基础报告不存在")
        report = json.loads(report_row["report_json"])
        merged = merge_ai_result(report, result)
        connection.execute(
            "UPDATE reports SET status = 'ready', report_json = ?, updated_at = ? WHERE dataset_id = ?",
            (json.dumps(merged, ensure_ascii=False, sort_keys=True), updated_at, dataset_id),
        )

    @staticmethod
    def _validate_active_lease(
        row: sqlite3.Row,
        source_hash: str,
        lease_token: str,
        now_text: str,
    ) -> None:
        """校验任务状态、数据版本和租约。"""

        if row["status"] != "processing":
            raise TaskConflictError(f"任务当前状态不能提交：{row['status']}")
        if row["source_hash"] != source_hash:
            raise TaskConflictError("任务数据版本已经变化")
        if row["lease_token"] != lease_token:
            raise TaskConflictError("任务租约无效")
        if not row["lease_expires_at"] or row["lease_expires_at"] < now_text:
            raise TaskConflictError("任务租约已经过期")

    def _connect(self) -> sqlite3.Connection:
        """创建启用字典行和外键约束的 SQLite 连接。"""

        return self.database.connect()
