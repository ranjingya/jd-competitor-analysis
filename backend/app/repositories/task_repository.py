"""使用 SQLite 持久化后端内部 AI 执行记录。"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import Database
from ..report_merge import merge_ai_result


LOGGER = logging.getLogger(__name__)


class TaskConflictError(RuntimeError):
    """任务状态或数据版本发生冲突。"""


@dataclass(frozen=True)
class TaskStartResult:
    """保存内部 AI 执行启动结果。"""

    analysis_id: str
    should_execute: bool


def _utc_now_text() -> str:
    """返回带时区的当前 UTC 时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskRepository:
    """管理后端内部 AI 执行记录。"""

    def __init__(self, database: Database | Path) -> None:
        self.database = database if isinstance(database, Database) else Database(database)

    def initialize(self) -> None:
        """初始化统一数据库。

        功能说明：创建持久化目录、三张业务表和索引，已有数据库执行兼容迁移。
        返回值：无。
        """

        self.database.initialize()

    def start(
        self,
        report_id: str,
        dataset_id: str,
        source_hash: str,
        payload: dict[str, Any],
        model: str,
        analysis_id: str | None = None,
    ) -> TaskStartResult:
        """启动一次内部 AI 分析。

        功能说明：相同输入已完成时直接复用；失败或中断时复用原记录重试；输入变化时将旧记录标记为 expired 并创建 processing 记录。
        参数 report_id：AI 结果最终写入的唯一报告 ID。
        参数 dataset_id：本次分析所属标准化数据集 ID。
        参数 source_hash：AI 输入的稳定内容哈希。
        参数 payload：只包含模型分析所需事实的结构化输入。
        参数 model：本次调用使用的模型标识。
        参数 analysis_id：可选执行记录 ID；为空时自动生成。
        返回值：执行记录 ID 与本次是否需要调用模型。
        """

        task_id = analysis_id or str(uuid.uuid4())
        now = _utc_now_text()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            report = connection.execute(
                "SELECT report_id FROM reports WHERE report_id = ? AND dataset_id = ?",
                (report_id, dataset_id),
            ).fetchone()
            if report is None:
                raise TaskConflictError("AI 执行关联的当前报告或数据版本不存在")
            existing = connection.execute(
                """
                SELECT analysis_id, dataset_id, source_hash, status
                FROM analysis_tasks
                WHERE report_id = ? AND status <> 'expired'
                """,
                (report_id,),
            ).fetchone()
            if existing is not None and (
                existing["dataset_id"] == dataset_id
                and existing["source_hash"] == source_hash
            ):
                existing_id = str(existing["analysis_id"])
                if existing["status"] == "completed":
                    connection.commit()
                    LOGGER.info(
                        "相同 AI 输入已完成，复用结果：analysis_id=%s，report_id=%s",
                        existing_id,
                        report_id,
                    )
                    return TaskStartResult(existing_id, False)
                connection.execute(
                    """
                    UPDATE analysis_tasks
                    SET model = ?, payload_json = ?, status = 'processing', result_json = NULL,
                        attempt_count = attempt_count + 1, error_message = NULL,
                        updated_at = ?, completed_at = NULL
                    WHERE analysis_id = ?
                    """,
                    (model, json.dumps(payload, ensure_ascii=False), now, existing_id),
                )
                connection.commit()
                LOGGER.info("AI 分析重新执行：analysis_id=%s，model=%s", existing_id, model)
                return TaskStartResult(existing_id, True)
            if existing is not None:
                connection.execute(
                    "UPDATE analysis_tasks SET status = 'expired', updated_at = ? WHERE analysis_id = ?",
                    (now, existing["analysis_id"]),
                )
                LOGGER.info(
                    "旧 AI 执行记录已标记过期：analysis_id=%s，report_id=%s",
                    existing["analysis_id"],
                    report_id,
                )
            connection.execute(
                """
                INSERT INTO analysis_tasks (
                    analysis_id, report_id, dataset_id, model, source_hash,
                    payload_json, status, attempt_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'processing', 1, ?, ?)
                """,
                (
                    task_id,
                    report_id,
                    dataset_id,
                    model,
                    source_hash,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        LOGGER.info(
            "AI 分析执行已创建：analysis_id=%s，report_id=%s，model=%s",
            task_id,
            report_id,
            model,
        )
        return TaskStartResult(task_id, True)

    def complete(self, analysis_id: str, result: dict[str, Any]) -> None:
        """完成内部 AI 分析。

        功能说明：在同一事务中校验并保存 AI 原始结果、合并基础报告，将任务和报告分别标记为 completed、ready。
        参数 analysis_id：需要完成的内部执行记录 ID。
        参数 result：模型返回的总结、发现和建议。
        返回值：无。
        """

        result_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
        now = _utc_now_text()
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
                if row["result_json"] == result_json:
                    connection.commit()
                    return
                raise TaskConflictError("AI 执行已经完成，不能覆盖已有结果")
            if row["status"] != "processing":
                raise TaskConflictError(f"AI 执行当前状态不能完成：{row['status']}")
            self._merge_report(connection, row["report_id"], row["dataset_id"], result, now)
            connection.execute(
                """
                UPDATE analysis_tasks
                SET status = 'completed', result_json = ?, error_message = NULL,
                    updated_at = ?, completed_at = ?
                WHERE analysis_id = ?
                """,
                (result_json, now, now, analysis_id),
            )
            connection.commit()
            LOGGER.info("AI 分析执行已完成：analysis_id=%s", analysis_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail(self, analysis_id: str, error_message: str) -> None:
        """记录内部 AI 分析失败。

        功能说明：保存可排查错误，并将当前数据版本的报告标记为 ai_failed，下一次日任务可复用该记录重试。
        参数 analysis_id：失败的内部执行记录 ID。
        参数 error_message：本次调用失败的简洁原因。
        返回值：无。
        """

        now = _utc_now_text()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM analysis_tasks WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(analysis_id)
            if row["status"] != "processing":
                raise TaskConflictError(f"AI 执行当前状态不能失败：{row['status']}")
            report_update = connection.execute(
                """
                UPDATE reports
                SET status = 'ai_failed', updated_at = ?
                WHERE report_id = ? AND dataset_id = ?
                """,
                (now, row["report_id"], row["dataset_id"]),
            )
            if report_update.rowcount != 1:
                raise TaskConflictError("AI 执行所属基础报告不存在")
            connection.execute(
                """
                UPDATE analysis_tasks
                SET status = 'failed', error_message = ?, updated_at = ?
                WHERE analysis_id = ?
                """,
                (error_message[:4000], now, analysis_id),
            )
            connection.commit()
            LOGGER.warning("AI 分析执行失败：analysis_id=%s，error=%s", analysis_id, error_message)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_recent(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """读取最近的内部 AI 执行摘要。

        功能说明：供后端测试和本地排查使用，不作为 Web API 对外开放。
        参数 status：可选执行状态筛选条件。
        参数 limit：最多返回的记录数量。
        返回值：包含日期、商品对、模型、状态和时间的摘要列表。
        """

        conditions = "WHERE task.status = ?" if status else ""
        parameters: tuple[Any, ...] = (status, limit) if status else (limit,)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    task.analysis_id, task.report_id, task.dataset_id,
                    dataset.report_date, dataset.compare_number,
                    dataset.self_spu, dataset.competitor_spu,
                    task.model, task.status, task.attempt_count,
                    task.created_at, task.updated_at, task.completed_at,
                    task.error_message
                FROM analysis_tasks AS task
                JOIN analysis_datasets AS dataset ON dataset.dataset_id = task.dataset_id
                {conditions}
                ORDER BY task.created_at DESC, task.analysis_id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _merge_report(
        connection: sqlite3.Connection,
        report_id: str,
        dataset_id: str,
        result: dict[str, Any],
        updated_at: str,
    ) -> None:
        """在当前事务中合并并更新任务所属报告。"""

        report_row = connection.execute(
            "SELECT report_json FROM reports WHERE report_id = ? AND dataset_id = ?",
            (report_id, dataset_id),
        ).fetchone()
        if report_row is None:
            raise TaskConflictError("AI 执行所属基础报告不存在")
        report = json.loads(report_row["report_json"])
        merged = merge_ai_result(report, result)
        connection.execute(
            """
            UPDATE reports
            SET status = 'ready', report_json = ?, updated_at = ?
            WHERE report_id = ? AND dataset_id = ?
            """,
            (json.dumps(merged, ensure_ascii=False, sort_keys=True), updated_at, report_id, dataset_id),
        )

    def _connect(self) -> sqlite3.Connection:
        """创建启用字典行和外键约束的 SQLite 连接。"""

        return self.database.connect()
