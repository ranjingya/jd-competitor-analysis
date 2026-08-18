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

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        """初始化任务数据库。

        功能说明：创建持久化目录和 AI 任务表，已有数据库保持原数据不变。
        返回值：无。
        """

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_tasks (
                    analysis_id TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    status TEXT NOT NULL,
                    worker_id TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status_created "
                "ON analysis_tasks(status, created_at)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_tasks_source_hash "
                "ON analysis_tasks(source_hash)"
            )
        LOGGER.info("AI 任务数据库初始化完成：%s", self.database_path)

    def enqueue(
        self,
        source_hash: str,
        payload: dict[str, Any],
        analysis_id: str | None = None,
    ) -> str:
        """创建待分析任务。

        功能说明：把后端脚本生成的结构化事实保存为 pending 任务，供 Mac Codex 后续领取。
        参数 source_hash：当前分析输入的稳定内容哈希。
        参数 payload：只包含分析所需事实的结构化输入。
        参数 analysis_id：可选任务 ID；为空时自动生成。
        返回值：创建后的任务 ID。
        """

        task_id = analysis_id or str(uuid.uuid4())
        now = _iso(_utc_now())
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO analysis_tasks (
                        analysis_id, source_hash, payload_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (task_id, source_hash, json.dumps(payload, ensure_ascii=False), now, now),
                )
            except sqlite3.IntegrityError as error:
                existing = connection.execute(
                    "SELECT analysis_id FROM analysis_tasks WHERE source_hash = ?",
                    (source_hash,),
                ).fetchone()
                if existing is None:
                    raise error
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
                SELECT analysis_id, source_hash, payload_json
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

        功能说明：校验任务版本和有效租约后原子保存 AI 结果；相同结果的重复提交视为成功。
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
                    connection.commit()
                    return
                raise TaskConflictError("任务已经完成，不能覆盖已有 AI 结果")
            self._validate_active_lease(row, source_hash, lease_token, now_text)
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

        功能说明：校验当前租约后保存失败原因，避免不完整 AI 结果进入正式报告。
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

        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
