"""按固定字段持久化并读取 Web 看板报告。"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

from jd_competitor_analysis.report import build_tabs, gap_text, relative_gap_pct

from ..database import Database, utc_now_text


LOGGER = logging.getLogger(__name__)
REPORT_STATUSES = {"pending_ai", "ready", "ai_failed"}
GRANULARITIES = {"day", "week", "month"}
REPORT_TOP_LEVEL_FIELDS = {
    "schema_version", "meta", "source_files", "self_validation",
    "competitor_core_conversions", "comparison", "core_metrics", "traffic_sources",
    "keywords", "customer_profile", "promotion", "tabs", "ai_findings",
    "ai_recommendations", "risks",
}
META_FIELDS = {
    "title", "period", "period_start", "period_end", "period_key", "granularity",
    "self_name", "self_spu", "self_product", "competitor_name", "competitor_spu",
    "competitor_product", "summary", "summary_detail", "weakness_summary",
    "weakness_summary_detail", "deterministic_summary",
    "deterministic_weakness_summary", "generated_at", "source_report_ids",
}
CORE_FIELDS = {
    "gmv": ("成交金额", "", "self_gmv", "competitor_gmv"),
    "visitors": ("访客数", "", "self_visitors", "competitor_visitors"),
    "conversion_rate": (
        "成交转化率", "%", "self_conversion_rate", "competitor_conversion_rate"
    ),
    "customer_price": ("成交客单价", "", "self_aov", "competitor_aov"),
}
CONTENT_COLUMNS = (
    "source_report_ids_json", "schema_version", "self_name", "self_image_url",
    "competitor_name", "competitor_image_url", "self_gmv", "competitor_gmv",
    "self_visitors", "competitor_visitors", "self_buyers", "competitor_buyers",
    "self_conversion_rate", "competitor_conversion_rate", "self_aov",
    "competitor_aov", "advantage_summary", "weakness_summary",
    "advantage_detail_json", "weakness_detail_json", "ai_findings_json",
    "ai_recommendations_json", "traffic_sources_json", "traffic_keywords_json",
    "customer_profile_json", "promotion_json", "risks_json", "audit_json",
    "quality_status", "generated_at",
)


def _json_text(value: Any) -> str:
    """把模块数据转换为稳定 JSON 文本。"""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_value(row: sqlite3.Row, column: str, default: Any) -> Any:
    """读取 JSON 字段并在空值时返回默认结构。"""

    raw = row[column]
    return json.loads(raw) if raw else default


def _number(value: Any) -> float | None:
    """把数据库或报告值转换为可存储数值。"""

    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_values(report: dict[str, Any]) -> dict[str, float | None]:
    """从报告核心对比中提取数据库固定指标字段。"""

    comparison = {
        str(item.get("metric_id")): item
        for item in report.get("comparison", [])
        if isinstance(item, dict)
    }
    cards = {
        str(item.get("id")): item
        for item in report.get("core_metrics", [])
        if isinstance(item, dict)
    }
    values: dict[str, float | None] = {}
    for metric_id, (_, unit, self_column, competitor_column) in CORE_FIELDS.items():
        comparison_item = comparison.get(metric_id, {})
        card = cards.get(metric_id, {})
        self_value = _number(comparison_item.get("self_value"))
        competitor_value = _number(comparison_item.get("competitor_value"))
        if self_value is None:
            self_value = _number(card.get("self_value"))
            if unit == "%" and self_value is not None:
                self_value /= 100
        if competitor_value is None:
            competitor_value = _number(card.get("competitor_value"))
            if unit == "%" and competitor_value is not None:
                competitor_value /= 100
        values[self_column] = self_value
        values[competitor_column] = competitor_value
    values["self_buyers"] = (
        values["self_visitors"] * values["self_conversion_rate"]
        if values["self_visitors"] is not None and values["self_conversion_rate"] is not None
        else None
    )
    values["competitor_buyers"] = (
        values["competitor_visitors"] * values["competitor_conversion_rate"]
        if values["competitor_visitors"] is not None
        and values["competitor_conversion_rate"] is not None
        else None
    )
    return values


def _build_core_metrics(row: sqlite3.Row) -> list[dict[str, Any]]:
    """从数据库核心指标字段生成前端指标卡。"""

    cards = []
    for metric_id, (label, unit, self_column, competitor_column) in CORE_FIELDS.items():
        raw_self = _number(row[self_column])
        raw_competitor = _number(row[competitor_column])
        self_value = raw_self * 100 if unit == "%" and raw_self is not None else raw_self
        competitor_value = (
            raw_competitor * 100 if unit == "%" and raw_competitor is not None else raw_competitor
        )
        comparable = raw_self is not None and raw_competitor is not None
        metric_status = "advantage" if comparable and raw_self >= raw_competitor else "warning"
        cards.append(
            {
                "id": metric_id,
                "label": label,
                "unit": unit,
                "self_value": self_value,
                "competitor_value": competitor_value,
                "gap_value": self_value - competitor_value if comparable else None,
                "gap_rate_pct": (
                    None
                    if unit == "%" or not comparable
                    else relative_gap_pct(raw_self, raw_competitor)
                ),
                "gap_mode": "percentage_point" if unit == "%" else "relative",
                "gap_text": gap_text(label, raw_self, raw_competitor),
                "status": metric_status,
                "priority": "高" if metric_status == "warning" else "低",
            }
        )
    return cards


def _report_entry(row: sqlite3.Row) -> dict[str, Any]:
    """把报告数据库行转换为前端导航使用的轻量条目。"""

    granularity = str(row["granularity"])
    start_date = str(row["start_date"])
    end_date = str(row["end_date"])
    period_key = (
        f"day:{start_date}"
        if granularity == "day"
        else f"{granularity}:{start_date}:{end_date}"
    )
    return {
        "report_id": row["report_id"],
        "dataset_id": row["dataset_id"],
        "period": start_date,
        "period_key": period_key,
        "start_date": start_date,
        "end_date": end_date,
        "self_spu": row["self_spu"],
        "competitor_spu": row["competitor_spu"],
        "self_name": row["self_name"],
        "self_image_url": row["self_image_url"],
        "competitor_name": row["competitor_name"],
        "competitor_image_url": row["competitor_image_url"],
        "quality_status": row["quality_status"],
        "status": row["status"],
        "title": "竞品准真实值看板",
        "summary": row["advantage_summary"],
        "path": f"/api/reports/{row['report_id']}",
        "updated_at": row["updated_at"],
    }


def _validate_period_context(granularity: str, context: str) -> None:
    """校验周期选择器上下文是否符合当前粒度。"""

    expected_length = 4 if granularity == "month" else 7
    if len(context) != expected_length:
        raise ValueError("月报上下文必须为 YYYY，日报和周报上下文必须为 YYYY-MM")
    try:
        date.fromisoformat(f"{context}-01" if expected_length == 7 else f"{context}-01-01")
    except ValueError as error:
        raise ValueError("周期上下文格式无效") from error


class ReportRepository:
    """保存分字段报告并提供按 ID 与周期的数据库查询。"""

    def __init__(self, database: Database | Path) -> None:
        """保存统一数据库实例。

        参数 database：统一数据库实例或兼容测试使用的数据库路径。
        """

        self.database = database if isinstance(database, Database) else Database(database)

    def initialize(self) -> None:
        """初始化统一数据库。"""

        self.database.initialize()

    def sync_product_images(
        self,
        product_images: dict[str, dict[str, Any]],
    ) -> dict[str, int]:
        """把商品主图配置同步到已有报告。

        功能说明：按 SPU 更新报告中的本品和竞品主图字段，仅处理配置中出现的商品，
        并在同一事务中完成全部更新。
        参数 product_images：按商品 ID 索引且已完成校验的主图配置。
        返回值：包含配置商品数、本品字段更新数、竞品字段更新数和总更新数的摘要。
        """

        started_at = perf_counter()
        self_updated = 0
        competitor_updated = 0
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            try:
                for product_id, asset in product_images.items():
                    image_url = asset.get("image_url")
                    self_updated += connection.execute(
                        """
                        UPDATE reports
                        SET self_image_url = ?
                        WHERE self_spu = ? AND self_image_url IS NOT ?
                        """,
                        (image_url, product_id, image_url),
                    ).rowcount
                    competitor_updated += connection.execute(
                        """
                        UPDATE reports
                        SET competitor_image_url = ?
                        WHERE competitor_spu = ? AND competitor_image_url IS NOT ?
                        """,
                        (image_url, product_id, image_url),
                    ).rowcount
            except Exception:
                connection.rollback()
                raise
            connection.commit()
        summary = {
            "products": len(product_images),
            "self_reports": self_updated,
            "competitor_reports": competitor_updated,
            "updated_fields": self_updated + competitor_updated,
        }
        LOGGER.info(
            "商品主图同步完成：products=%s，self_reports=%s，competitor_reports=%s，耗时=%.3fs",
            summary["products"],
            summary["self_reports"],
            summary["competitor_reports"],
            perf_counter() - started_at,
        )
        return summary

    def upsert(
        self,
        dataset_id: str | None,
        report: dict[str, Any],
        status: str = "pending_ai",
        report_id: str | None = None,
    ) -> str:
        """创建或更新一个业务周期的报告。

        功能说明：把完整内存报告拆成固定字段和模块 JSON；同一周期和商品对只保留一份报告。
        参数 dataset_id：日报所属日数据集 ID；周报和月报使用空值。
        参数 report：确定性分析或已完成 AI 合并的报告对象。
        参数 status：报告状态。
        参数 report_id：可选报告 ID。
        返回值：新建或已存在的报告 ID。
        """

        if status not in REPORT_STATUSES:
            raise ValueError(f"报告状态无效：{status}")
        selected_report_id = report_id or str(uuid.uuid4())
        now = utc_now_text()
        with self.database.connection() as connection:
            scope = self._resolve_scope(connection, dataset_id, report)
            content = self._report_content(connection, dataset_id, report)
            existing = connection.execute(
                """
                SELECT report_id, dataset_id, status
                FROM reports
                WHERE granularity = ? AND start_date = ? AND end_date = ?
                  AND self_spu = ? AND competitor_spu = ?
                """,
                scope,
            ).fetchone()
            if existing is not None:
                if (
                    existing["dataset_id"] == dataset_id
                    and status == "pending_ai"
                    and existing["status"] in {"ready", "ai_failed"}
                ):
                    LOGGER.info(
                        "相同数据集报告已处于 AI 终态，保留现有内容：report_id=%s，status=%s",
                        existing["report_id"], existing["status"],
                    )
                    return str(existing["report_id"])
                self._update_report(
                    connection, str(existing["report_id"]), dataset_id, status, content, now
                )
                LOGGER.info("报告已更新：report_id=%s，status=%s", existing["report_id"], status)
                return str(existing["report_id"])
            columns = (
                "report_id", "dataset_id", "granularity", "start_date", "end_date",
                "self_spu", "competitor_spu", *CONTENT_COLUMNS, "status", "created_at",
                "updated_at",
            )
            values = (
                selected_report_id, dataset_id, *scope,
                *(content[column] for column in CONTENT_COLUMNS), status, now, now,
            )
            try:
                connection.execute(
                    f"INSERT INTO reports ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    values,
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
                "SELECT report_date, self_spu, competitor_spu FROM analysis_datasets WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
            if dataset is None:
                raise FileNotFoundError(dataset_id)
            report_date = str(dataset["report_date"])
            return (
                "day", report_date, report_date,
                str(dataset["self_spu"]), str(dataset["competitor_spu"]),
            )
        meta = report.get("meta")
        if not isinstance(meta, dict):
            raise ValueError("周报或月报缺少 meta")
        scope = (
            str(meta.get("granularity") or ""), str(meta.get("period_start") or ""),
            str(meta.get("period_end") or ""), str(meta.get("self_spu") or ""),
            str(meta.get("competitor_spu") or ""),
        )
        granularity, start_date, end_date, self_spu, competitor_spu = scope
        if granularity not in GRANULARITIES:
            raise ValueError(f"报告粒度无效：{granularity}")
        if not all((start_date, end_date, self_spu, competitor_spu)):
            raise ValueError("独立报告缺少日期范围或商品对")
        if granularity == "day" and start_date != end_date:
            raise ValueError("独立日报的开始日期和结束日期必须相同")
        return scope

    @staticmethod
    def _report_content(
        connection: sqlite3.Connection,
        dataset_id: str | None,
        report: dict[str, Any],
    ) -> dict[str, Any]:
        """把内存报告拆成数据库字段。

        功能说明：提取商品、核心指标、AI 分析和四个明细模块，并保留必要审计数据。
        参数 connection：当前数据库连接，用于读取日报数据质量。
        参数 dataset_id：日报数据集 ID；独立周期报告为空。
        参数 report：确定性分析或完整报告对象。
        返回值：以报告表内容字段名为键的字典。
        """

        meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
        self_product = meta.get("self_product") if isinstance(meta.get("self_product"), dict) else {}
        competitor_product = (
            meta.get("competitor_product")
            if isinstance(meta.get("competitor_product"), dict)
            else {}
        )
        metric_values = _metric_values(report)
        quality_status = str(report.get("quality_status") or "ready")
        if dataset_id is not None:
            dataset = connection.execute(
                "SELECT quality_status FROM analysis_datasets WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
            if dataset is None:
                raise FileNotFoundError(dataset_id)
            quality_status = str(dataset["quality_status"])
        audit = {
            "title": meta.get("title"),
            "period": meta.get("period"),
            "period_key": meta.get("period_key"),
            "deterministic_summary": meta.get("deterministic_summary", meta.get("summary")),
            "deterministic_weakness_summary": meta.get(
                "deterministic_weakness_summary", meta.get("weakness_summary")
            ),
            "source_files": report.get("source_files", []),
            "self_validation": report.get("self_validation", []),
            "competitor_core_conversions": report.get("competitor_core_conversions", []),
            "comparison": report.get("comparison", []),
            "meta_extra": {key: value for key, value in meta.items() if key not in META_FIELDS},
            "extra": {
                key: value for key, value in report.items() if key not in REPORT_TOP_LEVEL_FIELDS
            },
        }
        source_report_ids = meta.get("source_report_ids", [])
        if not isinstance(source_report_ids, list):
            source_report_ids = []
        return {
            "source_report_ids_json": _json_text(source_report_ids),
            "schema_version": str(report.get("schema_version") or "1.0"),
            "self_name": self_product.get("name") or meta.get("self_name"),
            "self_image_url": self_product.get("image_url"),
            "competitor_name": competitor_product.get("name") or meta.get("competitor_name"),
            "competitor_image_url": competitor_product.get("image_url"),
            **metric_values,
            "advantage_summary": meta.get("summary"),
            "weakness_summary": meta.get("weakness_summary"),
            "advantage_detail_json": _json_text(meta.get("summary_detail") or []),
            "weakness_detail_json": _json_text(meta.get("weakness_summary_detail") or []),
            "ai_findings_json": _json_text(report.get("ai_findings") or []),
            "ai_recommendations_json": _json_text(report.get("ai_recommendations") or []),
            "traffic_sources_json": _json_text(report.get("traffic_sources") or []),
            "traffic_keywords_json": _json_text(report.get("keywords") or {}),
            "customer_profile_json": _json_text(report.get("customer_profile") or {}),
            "promotion_json": _json_text(report.get("promotion") or {}),
            "risks_json": _json_text(report.get("risks") or []),
            "audit_json": _json_text(audit),
            "quality_status": quality_status,
            "generated_at": meta.get("generated_at"),
        }

    @staticmethod
    def _update_report(
        connection: sqlite3.Connection,
        report_id: str,
        dataset_id: str | None,
        status: str,
        content: dict[str, Any],
        updated_at: str,
    ) -> None:
        """更新报告全部内容字段。"""

        assignments = ["dataset_id = ?", *(f"{column} = ?" for column in CONTENT_COLUMNS)]
        assignments.extend(["status = ?", "updated_at = ?"])
        connection.execute(
            f"UPDATE reports SET {','.join(assignments)} WHERE report_id = ?",
            (
                dataset_id, *(content[column] for column in CONTENT_COLUMNS),
                status, updated_at, report_id,
            ),
        )

    def activate_pending(
        self,
        report_id: str,
        dataset_id: str | None,
        report: dict[str, Any],
    ) -> None:
        """激活新 AI 输入对应的基础报告。

        功能说明：把当前基础报告按字段覆盖唯一报告，并标记为等待 AI。
        参数 report_id：需要更新的报告 ID。
        参数 dataset_id：日报数据集 ID；周月报告使用空值。
        参数 report：尚未合并 AI 结果的基础报告。
        返回值：无。
        """

        now = utc_now_text()
        with self.database.connection() as connection:
            content = self._report_content(connection, dataset_id, report)
            exists = connection.execute(
                "SELECT 1 FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            if exists is None:
                raise FileNotFoundError(report_id)
            self._update_report(connection, report_id, dataset_id, "pending_ai", content, now)
        LOGGER.info("报告已进入 AI 待处理状态：report_id=%s，dataset_id=%s", report_id, dataset_id)

    def get(self, report_id: str) -> dict[str, Any]:
        """按报告 ID 读取兼容前端的完整报告。

        功能说明：读取分字段报告并组装为 Web 当前使用的完整 JSON 契约。
        参数 report_id：报告 ID。
        返回值：完整报告对象。
        """

        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
        if row is None:
            raise FileNotFoundError(report_id)
        return self._row_to_report(row)

    def get_record(self, report_id: str) -> dict[str, Any]:
        """读取报告索引字段和兼容完整报告。

        功能说明：同时返回数据库索引字段和组装后的完整报告，供内部流程与测试使用。
        参数 report_id：报告 ID。
        返回值：报告数据库摘要及完整报告。
        """

        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
        if row is None:
            raise FileNotFoundError(report_id)
        return {
            "report_id": row["report_id"], "dataset_id": row["dataset_id"],
            "granularity": row["granularity"], "start_date": row["start_date"],
            "end_date": row["end_date"], "self_spu": row["self_spu"],
            "competitor_spu": row["competitor_spu"],
            "quality_status": row["quality_status"], "status": row["status"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "report": self._row_to_report(row),
        }

    @staticmethod
    def _row_to_report(row: sqlite3.Row) -> dict[str, Any]:
        """把分字段数据库记录组装为现有前端报告契约。

        功能说明：恢复元数据、指标卡、分析模块和页面 tabs，同时保留审计扩展字段。
        参数 row：报告表完整数据库记录。
        返回值：Web 可直接消费的报告对象。
        """

        audit = _json_value(row, "audit_json", {})
        traffic = _json_value(row, "traffic_sources_json", [])
        keywords = _json_value(row, "traffic_keywords_json", {})
        profile = _json_value(row, "customer_profile_json", {})
        report = dict(audit.get("extra") or {})
        meta = dict(audit.get("meta_extra") or {})
        granularity = str(row["granularity"])
        start_date = str(row["start_date"])
        end_date = str(row["end_date"])
        period_key = (
            f"day:{start_date}" if granularity == "day"
            else f"{granularity}:{start_date}:{end_date}"
        )
        meta.update(
            {
                "title": audit.get("title") or "竞品准真实值看板",
                "period": audit.get("period") or start_date,
                "period_start": start_date,
                "period_end": end_date,
                "period_key": audit.get("period_key") or period_key,
                "granularity": granularity,
                "self_name": row["self_name"],
                "self_spu": row["self_spu"],
                "self_product": {
                    "id": row["self_spu"], "name": row["self_name"],
                    "image_url": row["self_image_url"],
                },
                "competitor_name": row["competitor_name"],
                "competitor_spu": row["competitor_spu"],
                "competitor_product": {
                    "id": row["competitor_spu"], "name": row["competitor_name"],
                    "image_url": row["competitor_image_url"],
                },
                "summary": row["advantage_summary"],
                "summary_detail": _json_value(row, "advantage_detail_json", []),
                "weakness_summary": row["weakness_summary"],
                "weakness_summary_detail": _json_value(row, "weakness_detail_json", []),
                "deterministic_summary": audit.get("deterministic_summary"),
                "deterministic_weakness_summary": audit.get("deterministic_weakness_summary"),
                "generated_at": row["generated_at"],
                "source_report_ids": _json_value(row, "source_report_ids_json", []),
            }
        )
        try:
            tabs = build_tabs(traffic, keywords, profile)
        except (KeyError, TypeError, ValueError):
            tabs = []
        report.update(
            {
                "schema_version": row["schema_version"], "meta": meta,
                "source_files": audit.get("source_files", []),
                "self_validation": audit.get("self_validation", []),
                "competitor_core_conversions": audit.get("competitor_core_conversions", []),
                "comparison": audit.get("comparison", []),
                "core_metrics": _build_core_metrics(row), "traffic_sources": traffic,
                "keywords": keywords, "customer_profile": profile,
                "promotion": _json_value(row, "promotion_json", {}), "tabs": tabs,
                "ai_findings": _json_value(row, "ai_findings_json", []),
                "ai_recommendations": _json_value(row, "ai_recommendations_json", []),
                "risks": _json_value(row, "risks_json", []),
            }
        )
        return report

    def get_skus(self, report_id: str) -> dict[str, Any]:
        """读取生成指定报告时使用的本品 SKU 构成。

        功能说明：日报读取当前数据集快照，周期报告合并来源日报快照，并按 SPU/SKU 去重。
        参数 report_id：报告 ID。
        返回值：包含周期、本品 SPU 和五字段 SKU 列表的对象。
        """

        with self.database.connection() as connection:
            report_row = connection.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
            if report_row is None:
                raise FileNotFoundError(report_id)
            dataset_rows = []
            if report_row["dataset_id"] is not None:
                dataset_row = connection.execute(
                    "SELECT dataset_id, self_product_json FROM analysis_datasets WHERE dataset_id = ?",
                    (report_row["dataset_id"],),
                ).fetchone()
                if dataset_row is not None:
                    dataset_rows.append(dataset_row)
            else:
                source_report_ids = _json_value(report_row, "source_report_ids_json", [])
                if source_report_ids:
                    placeholders = ",".join("?" for _ in source_report_ids)
                    dataset_rows = connection.execute(
                        f"""
                        SELECT dataset.dataset_id, dataset.self_product_json
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
            self_product = json.loads(dataset_row["self_product_json"])
            for item in self_product.get("sku_components", []):
                if not isinstance(item, dict):
                    continue
                component = {
                    "spu_id": item.get("spu_id"), "sku_id": item.get("sku_id"),
                    "barcode_69": item.get("barcode_69"),
                    "product_name": item.get("product_name"),
                    "specification": item.get("specification"),
                }
                key = (str(component["spu_id"] or ""), str(component["sku_id"] or ""))
                if all(key):
                    components[key] = component
        items = list(components.values())
        return {
            "report_id": str(report_row["report_id"]), "dataset_id": report_row["dataset_id"],
            "source_dataset_ids": source_dataset_ids,
            "granularity": str(report_row["granularity"]),
            "start_date": str(report_row["start_date"]), "end_date": str(report_row["end_date"]),
            "spu_id": str(report_row["self_spu"]), "sku_count": len(items), "items": items,
        }

    def list_product_pairs(self) -> dict[str, Any]:
        """返回商品对及各粒度最新报告。

        功能说明：每个商品对只返回日、周、月各一条最新报告及报告数量，供页面首次导航使用。
        返回值：包含商品对列表和最近更新时间的轻量对象。
        """

        with self.database.connection() as connection:
            updated_at = connection.execute(
                "SELECT MAX(updated_at) FROM reports"
            ).fetchone()[0]
            rows = connection.execute(
                """
                WITH ranked_reports AS (
                    SELECT report_id, dataset_id, granularity, start_date, end_date,
                           self_spu, competitor_spu, self_name, self_image_url,
                           competitor_name, competitor_image_url, advantage_summary,
                           quality_status, status, updated_at,
                           COUNT(*) OVER (
                               PARTITION BY self_spu, competitor_spu, granularity
                           ) AS report_count,
                           ROW_NUMBER() OVER (
                               PARTITION BY self_spu, competitor_spu, granularity
                               ORDER BY start_date DESC, end_date DESC,
                                        updated_at DESC, report_id DESC
                           ) AS report_rank
                    FROM reports
                )
                SELECT * FROM ranked_reports
                WHERE report_rank = 1
                ORDER BY updated_at DESC, self_spu, competitor_spu, granularity
                """
            ).fetchall()
        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            pair_key = (str(row["self_spu"]), str(row["competitor_spu"]))
            pair = pairs.setdefault(
                pair_key,
                {
                    "self_spu": pair_key[0],
                    "competitor_spu": pair_key[1],
                    "self_name": row["self_name"],
                    "self_image_url": row["self_image_url"],
                    "competitor_name": row["competitor_name"],
                    "competitor_image_url": row["competitor_image_url"],
                    "latest_reports": {"day": None, "week": None, "month": None},
                    "report_counts": {"day": 0, "week": 0, "month": 0},
                },
            )
            granularity = str(row["granularity"])
            pair["latest_reports"][granularity] = _report_entry(row)
            pair["report_counts"][granularity] = int(row["report_count"])
        items = list(pairs.values())
        items.sort(key=lambda item: (str(item["self_spu"]), str(item["competitor_spu"])))
        return {
            "updated_at": str(updated_at) if updated_at is not None else None,
            "items": items,
        }

    def list_periods(
        self,
        self_spu: str,
        competitor_spu: str,
        granularity: str,
        context: str,
    ) -> dict[str, Any]:
        """返回指定商品对和日历上下文中的可用报告。

        功能说明：日报和周报按 YYYY-MM 查询，月报按 YYYY 查询，同时返回可导航上下文。
        参数 self_spu：本品 SPU。
        参数 competitor_spu：竞品 SPU。
        参数 granularity：day、week 或 month。
        参数 context：日报/周报月份 YYYY-MM，或月报年份 YYYY。
        返回值：当前上下文的轻量报告条目、全部可用上下文及报告总数。
        """

        if granularity not in GRANULARITIES:
            raise ValueError(f"不支持的报告粒度：{granularity}")
        _validate_period_context(granularity, context)
        context_length = 4 if granularity == "month" else 7
        with self.database.connection() as connection:
            contexts = [
                str(row["period_context"])
                for row in connection.execute(
                    f"""
                    SELECT DISTINCT substr(start_date, 1, {context_length}) AS period_context
                    FROM reports
                    WHERE self_spu = ? AND competitor_spu = ? AND granularity = ?
                    ORDER BY period_context
                    """,
                    (self_spu, competitor_spu, granularity),
                ).fetchall()
            ]
            report_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM reports
                    WHERE self_spu = ? AND competitor_spu = ? AND granularity = ?
                    """,
                    (self_spu, competitor_spu, granularity),
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT report_id, dataset_id, granularity, start_date, end_date,
                       self_spu, competitor_spu, self_name, self_image_url,
                       competitor_name, competitor_image_url, advantage_summary,
                       quality_status, status, updated_at
                FROM reports
                WHERE self_spu = ? AND competitor_spu = ? AND granularity = ?
                  AND substr(start_date, 1, {context_length}) = ?
                ORDER BY start_date, end_date, updated_at, report_id
                """,
                (self_spu, competitor_spu, granularity, context),
            ).fetchall()
        return {
            "self_spu": self_spu,
            "competitor_spu": competitor_spu,
            "granularity": granularity,
            "context": context,
            "contexts": contexts,
            "report_count": report_count,
            "items": [_report_entry(row) for row in rows],
        }

    def read_trends(
        self,
        self_spu: str,
        competitor_spu: str,
        granularity: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """读取指定范围的轻量核心指标趋势。

        功能说明：只查询趋势图需要的四组固定指标，不读取五张分析表和 AI 内容。
        参数 self_spu：本品 SPU。
        参数 competitor_spu：竞品 SPU。
        参数 granularity：day、week 或 month。
        参数 start_date：报告开始日期下界。
        参数 end_date：报告开始日期上界。
        返回值：包含轻量报告数组的趋势对象。
        """

        if granularity not in GRANULARITIES:
            raise ValueError(f"不支持的报告粒度：{granularity}")
        try:
            parsed_start = date.fromisoformat(start_date)
            parsed_end = date.fromisoformat(end_date)
        except ValueError as error:
            raise ValueError("趋势日期格式必须为 YYYY-MM-DD") from error
        if parsed_start > parsed_end:
            raise ValueError("趋势开始日期不能晚于结束日期")
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT report_id, granularity, start_date, end_date,
                       self_gmv, competitor_gmv, self_visitors, competitor_visitors,
                       self_conversion_rate, competitor_conversion_rate,
                       self_aov, competitor_aov
                FROM reports
                WHERE self_spu = ? AND competitor_spu = ? AND granularity = ?
                  AND start_date BETWEEN ? AND ?
                ORDER BY start_date, end_date, report_id
                """,
                (self_spu, competitor_spu, granularity, start_date, end_date),
            ).fetchall()
        items = [
            {
                "report_id": row["report_id"],
                "meta": {
                    "period": row["start_date"],
                    "period_start": row["start_date"],
                    "period_end": row["end_date"],
                    "granularity": row["granularity"],
                },
                "core_metrics": _build_core_metrics(row),
            }
            for row in rows
        ]
        return {
            "self_spu": self_spu,
            "competitor_spu": competitor_spu,
            "granularity": granularity,
            "start_date": start_date,
            "end_date": end_date,
            "items": items,
        }

    def read_report(self, granularity: str, start_date: str, end_date: str) -> dict[str, Any]:
        """按粒度和周期读取最新报告。

        功能说明：校验粒度和起止日期，定位唯一业务报告并组装完整前端契约。
        参数 granularity：day、week 或 month。
        参数 start_date：周期开始日期。
        参数 end_date：周期结束日期。
        返回值：完整报告对象。
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
                SELECT * FROM reports
                WHERE granularity = ? AND start_date = ? AND end_date = ?
                ORDER BY updated_at DESC, report_id LIMIT 1
                """,
                (granularity, start_date, end_date),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"{granularity}:{start_date}:{end_date}")
        return self._row_to_report(row)
