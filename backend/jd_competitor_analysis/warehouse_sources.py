"""读取 StarRocks 中的竞品对比数据和本品 SKU 日数据。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from .warehouse import _quote_table_name


LOGGER = logging.getLogger(__name__)
PRODUCT_ID_PATTERN = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class ProductPair:
    """表示一组本品 SPU 和竞品 SPU。"""

    self_spu: str
    competitor_spu: str

    @classmethod
    def parse(cls, compare_number: str) -> ProductPair:
        """解析数仓商品对编号。

        功能说明：把 `<本品SPU>+<竞品SPU>` 转换为具名商品对，并阻止模糊或非法编号进入查询。
        参数 compare_number：数仓 `compare_number` 字段或外部查询参数。
        返回值：包含本品 SPU 和竞品 SPU 的不可变对象。
        """

        parts = [part.strip() for part in str(compare_number).split("+")]
        if len(parts) != 2 or any(not PRODUCT_ID_PATTERN.fullmatch(part) for part in parts):
            raise ValueError(f"compare_number 必须是 <本品SPU>+<竞品SPU>：{compare_number}")
        if parts[0] == parts[1]:
            raise ValueError("compare_number 中的本品 SPU 和竞品 SPU 不能相同")
        return cls(self_spu=parts[0], competitor_spu=parts[1])

    @property
    def compare_number(self) -> str:
        """返回数仓使用的标准商品对编号。"""

        return f"{self.self_spu}+{self.competitor_spu}"


@dataclass(frozen=True)
class CompetitorTableSpec:
    """描述一张竞品对比来源表。"""

    source_id: str
    table_name: str


COMPETITOR_TABLES = (
    CompetitorTableSpec("core_metrics", "ods_rpa_jdzy_competitor_data_compare_f"),
    CompetitorTableSpec("traffic_sources", "ods_rpa_jdzy_traffic_source_compare_f"),
    CompetitorTableSpec("traffic_keywords", "ods_rpa_jdzy_traffic_keyword_compare_f"),
    CompetitorTableSpec("customer_profiles", "ods_rpa_jdzy_deal_customer_compare_f"),
    CompetitorTableSpec("promotion", "ods_rpa_jdzy_promotion_data_compare_f"),
)
SELF_SKU_TABLE = "ods_rpa_jd_jd_business_product_detail_f"
SELF_SKU_COLUMNS = (
    "dt",
    "sku_name",
    "sku_id",
    "brand",
    "category1",
    "category2",
    "category3",
    "shop_name",
    "business_model",
    "pv",
    "uv",
    "average_pv",
    "average_duration",
    "transaction_user",
    "transaction_conversion_rate",
    "transaction_order",
    "transaction_product",
    "transaction_amount",
    "transaction_atv",
    "cart_user",
    "cart_conversion_rate",
    "cart_product",
    "create_time",
    "time_granularity",
    "relevant_dt",
)


def parse_report_date(value: str | date) -> date:
    """解析日维度查询日期。"""

    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as error:
        raise ValueError(f"查询日期必须是 YYYY-MM-DD：{value}") from error


def normalize_sku_ids(values: Iterable[str | int | float]) -> tuple[int, ...]:
    """规范化用于本品明细查询的 SKU ID。

    功能说明：接受字符串或数值 SKU，清理数仓浮点展示形式，去重后返回稳定的整数参数。
    参数 values：SPU/SKU 映射提供的 SKU ID 集合。
    返回值：保持首次出现顺序的唯一 SKU 整数元组。
    """

    normalized: list[int] = []
    seen: set[int] = set()
    for raw_value in values:
        raw_text = str(raw_value).strip()
        if raw_text.endswith(".0"):
            raw_text = raw_text[:-2]
        if not PRODUCT_ID_PATTERN.fullmatch(raw_text):
            raise ValueError(f"SKU ID 必须是正整数：{raw_value}")
        sku_id = int(raw_text)
        if sku_id <= 0:
            raise ValueError(f"SKU ID 必须大于 0：{raw_value}")
        if sku_id not in seen:
            normalized.append(sku_id)
            seen.add(sku_id)
    if not normalized:
        raise ValueError("读取本品日数据前必须提供至少一个 SKU ID")
    return tuple(normalized)


def _decode_json_data(table_name: str, row: dict[str, Any]) -> dict[str, Any]:
    """解析竞品表的 json_data 对象。"""

    raw_value = row.get("json_data")
    if isinstance(raw_value, dict):
        return raw_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValueError(f"{table_name} id={row.get('id')} 的 json_data 为空或不是对象")
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{table_name} id={row.get('id')} 的 json_data 不是有效 JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{table_name} id={row.get('id')} 的 json_data 顶层必须是对象")
    return parsed


def _latest_load_rows(rows: list[dict[str, Any]], timestamp_field: str) -> list[dict[str, Any]]:
    """仅保留最新一次同步批次的记录，并按原始行 ID 升序排列。"""

    if not rows:
        return []
    latest_timestamp = max(str(row.get(timestamp_field) or "") for row in rows)
    latest_rows = [row for row in rows if str(row.get(timestamp_field) or "") == latest_timestamp]
    return sorted(latest_rows, key=lambda row: (row.get("id") is None, row.get("id")))


def read_competitor_sources(
    engine: Engine,
    product_pair: ProductPair,
    report_date: str | date,
) -> dict[str, list[dict[str, Any]]]:
    """读取一组商品对的五张竞品日数据。

    功能说明：使用同一个连接按固定顺序查询五张来源表，按最新同步批次去重并解析 `json_data`。
    参数 engine：已配置的 SQLAlchemy 数仓引擎。
    参数 product_pair：本品 SPU 与竞品 SPU 商品对。
    参数 report_date：日维度业务日期，格式为 YYYY-MM-DD 或 date。
    返回值：按 core_metrics、traffic_sources、traffic_keywords、customer_profiles、promotion 分组的数据。
    """

    selected_date = parse_report_date(report_date)
    datasets: dict[str, list[dict[str, Any]]] = {}
    LOGGER.info(
        "开始顺序读取竞品日数据：date=%s，compare_number=%s",
        selected_date,
        product_pair.compare_number,
    )
    with engine.connect() as connection:
        for table in COMPETITOR_TABLES:
            quoted_table = _quote_table_name(engine, table.table_name)
            query = text(
                f"SELECT id, dt, compare_number, json_data, updated_at "
                f"FROM {quoted_table} "
                "WHERE dt = :report_date AND compare_number = :compare_number "
                "ORDER BY updated_at DESC, id DESC"
            )
            rows = [
                dict(row)
                for row in connection.execute(
                    query,
                    {
                        "report_date": selected_date.isoformat(),
                        "compare_number": product_pair.compare_number,
                    },
                ).mappings()
            ]
            latest_rows = _latest_load_rows(rows, "updated_at")
            datasets[table.source_id] = [
                {
                    "id": row.get("id"),
                    "dt": row.get("dt"),
                    "compare_number": row.get("compare_number"),
                    "self_spu": product_pair.self_spu,
                    "competitor_spu": product_pair.competitor_spu,
                    "updated_at": row.get("updated_at"),
                    "data": _decode_json_data(table.table_name, row),
                }
                for row in latest_rows
            ]
            LOGGER.info(
                "竞品来源读取完成：source=%s，table=%s，rows=%s",
                table.source_id,
                table.table_name,
                len(latest_rows),
            )
    LOGGER.info("五张竞品日数据读取完成：date=%s", selected_date)
    return datasets


def read_self_sku_daily(
    engine: Engine,
    report_date: str | date,
    sku_ids: Iterable[str | int | float],
) -> list[dict[str, Any]]:
    """读取本品 SKU 日数据。

    功能说明：按业务日期和 SKU 列表读取自然日明细，并为同一 SKU 保留 create_time 最新的记录。
    参数 engine：已配置的 SQLAlchemy 数仓引擎。
    参数 report_date：日维度业务日期，格式为 YYYY-MM-DD 或 date。
    参数 sku_ids：当前本品 SPU 映射到的 SKU ID 集合。
    返回值：每个 SKU 最多一行的标准列明细，SKU ID 统一为字符串。
    """

    selected_date = parse_report_date(report_date)
    selected_sku_ids = normalize_sku_ids(sku_ids)
    quoted_table = _quote_table_name(engine, SELF_SKU_TABLE)
    quoted_columns = ", ".join(engine.dialect.identifier_preparer.quote(column) for column in SELF_SKU_COLUMNS)
    query = text(
        f"SELECT {quoted_columns} FROM {quoted_table} "
        "WHERE dt = :report_date AND sku_id IN :sku_ids "
        "AND time_granularity = :time_granularity "
        "ORDER BY create_time DESC"
    ).bindparams(bindparam("sku_ids", expanding=True))
    LOGGER.info("开始读取本品 SKU 日数据：date=%s，sku_count=%s", selected_date, len(selected_sku_ids))
    with engine.connect() as connection:
        rows = [
            dict(row)
            for row in connection.execute(
                query,
                {
                    "report_date": selected_date.isoformat(),
                    "sku_ids": selected_sku_ids,
                    "time_granularity": "natural_day",
                },
            ).mappings()
        ]

    latest_by_sku: dict[str, dict[str, Any]] = {}
    for row in rows:
        normalized_sku_id = str(int(float(row["sku_id"])))
        row["sku_id"] = normalized_sku_id
        current = latest_by_sku.get(normalized_sku_id)
        if current is None or str(row.get("create_time") or "") > str(current.get("create_time") or ""):
            latest_by_sku[normalized_sku_id] = row
    result = [latest_by_sku[sku_id] for sku_id in map(str, selected_sku_ids) if sku_id in latest_by_sku]
    LOGGER.info("本品 SKU 日数据读取完成：date=%s，rows=%s", selected_date, len(result))
    return result
