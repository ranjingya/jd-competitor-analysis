"""读取 StarRocks 中的竞品对比数据和本品 SKU 日数据。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from time import perf_counter
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

    def __post_init__(self) -> None:
        """校验本品和竞品 SPU。"""

        for field_name, value in (("self_spu", self.self_spu), ("competitor_spu", self.competitor_spu)):
            if not PRODUCT_ID_PATTERN.fullmatch(str(value).strip()):
                raise ValueError(f"{field_name} 必须是正整数商品 ID：{value}")
        if self.self_spu == self.competitor_spu:
            raise ValueError("本品 SPU 和竞品 SPU 不能相同")


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
DAY_GRANULARITY = "day"
SELF_SKU_DAY_GRANULARITY = "natural_day"
PRODUCT_ROLES = {"本品": "self", "竞品": "competitor"}
EXPECTED_JSON_FIELDS = {
    "core_metrics": frozenset(
        {
            "时间",
            "浏览量",
            "访客数",
            "加购人数",
            "成交单量",
            "成交金额",
            "成交客单价",
            "成交转化率",
            "成交商品件数",
            "搜索点击次数",
        }
    ),
    "traffic_sources": frozenset(
        {
            "时间",
            "访客数",
            "一级渠道",
            "二级渠道",
            "三级渠道",
            "成交金额",
            "成交客户数",
            "成交转化率",
            "访客数占比",
        }
    ),
    "traffic_keywords": frozenset({"日期", "关键词", "访客数", "商品名称", "成交金额"}),
    "customer_profiles": frozenset({"时间", "画像类型", "成交客户数占比"}),
    "promotion": frozenset(
        {
            "全站-全站交易额",
            "非全站-广告点击数",
            "全站-核心位置点击数",
            "非全站-广告总订单金额",
        }
    ),
}
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


def _compare_json_fields(source_id: str, data: dict[str, Any]) -> dict[str, list[str]]:
    """比较数仓 JSON 字段与当前适配字段。

    功能说明：记录字段新增、缺失或改名，不因字段变化中断整批读取。
    参数 source_id：五张来源表对应的内部来源 ID。
    参数 data：已经解析为对象的 `json_data`。
    返回值：按稳定顺序排列的缺失字段和新增字段。
    """

    expected = EXPECTED_JSON_FIELDS[source_id]
    actual = set(data)
    difference = {
        "missing": sorted(expected - actual),
        "extra": sorted(actual - expected),
    }
    return difference


def _row_id_sort_key(row: dict[str, Any]) -> tuple[int, int | str]:
    """生成兼容数值文本和普通文本的原始行 ID 排序键。"""

    value = row.get("id")
    try:
        return 0, int(str(value))
    except (TypeError, ValueError):
        return 1, str(value or "")


def _latest_load_rows(rows: list[dict[str, Any]], timestamp_field: str) -> list[dict[str, Any]]:
    """仅保留最新一次同步批次的记录，并按原始行 ID 升序排列。"""

    if not rows:
        return []
    latest_timestamp = max(str(row.get(timestamp_field) or "") for row in rows)
    latest_rows = [row for row in rows if str(row.get(timestamp_field) or "") == latest_timestamp]
    return sorted(latest_rows, key=_row_id_sort_key)


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

    started_at = perf_counter()
    selected_date = parse_report_date(report_date)
    datasets: dict[str, list[dict[str, Any]]] = {}
    LOGGER.info(
        "开始顺序读取竞品日数据：date=%s，self_spu=%s，competitor_spu=%s，granularity=%s",
        selected_date,
        product_pair.self_spu,
        product_pair.competitor_spu,
        DAY_GRANULARITY,
    )
    with engine.connect() as connection:
        for table in COMPETITOR_TABLES:
            source_started_at = perf_counter()
            quoted_table = _quote_table_name(engine, table.table_name)
            query = text(
                f"SELECT id, dt, start_dt, spu_id, competitor_spu_id, is_competitor, "
                f"time_granularity, json_data, updated_at "
                f"FROM {quoted_table} "
                "WHERE dt = :report_date AND start_dt = :report_date "
                "AND time_granularity = :time_granularity AND spu_id = :self_spu "
                "AND ((is_competitor = :self_role AND competitor_spu_id IS NULL) "
                "OR (is_competitor = :competitor_role AND competitor_spu_id = :competitor_spu)) "
                "ORDER BY updated_at DESC, id DESC"
            )
            rows = [
                dict(row)
                for row in connection.execute(
                    query,
                    {
                        "report_date": selected_date.isoformat(),
                        "time_granularity": DAY_GRANULARITY,
                        "self_spu": product_pair.self_spu,
                        "competitor_spu": product_pair.competitor_spu,
                        "self_role": "本品",
                        "competitor_role": "竞品",
                    },
                ).mappings()
            ]
            latest_rows = _latest_load_rows(rows, "updated_at")
            normalized_rows = []
            for row in latest_rows:
                role = PRODUCT_ROLES.get(str(row.get("is_competitor") or "").strip())
                if role is None:
                    LOGGER.warning(
                        "跳过无法识别商品角色的数仓记录：table=%s，id=%s，is_competitor=%s",
                        table.table_name,
                        row.get("id"),
                        row.get("is_competitor"),
                    )
                    continue
                data = _decode_json_data(table.table_name, row)
                normalized_rows.append(
                    {
                        "id": row.get("id"),
                        "dt": row.get("dt"),
                        "start_dt": row.get("start_dt"),
                        "self_spu": product_pair.self_spu,
                        "competitor_spu": product_pair.competitor_spu,
                        "product_role": role,
                        "time_granularity": DAY_GRANULARITY,
                        "updated_at": row.get("updated_at"),
                        "json_fields": _compare_json_fields(table.source_id, data),
                        "data": data,
                    }
                )
            changed_rows = [
                row
                for row in normalized_rows
                if row["json_fields"]["missing"] or row["json_fields"]["extra"]
            ]
            if changed_rows:
                missing_fields = sorted(
                    {
                        field
                        for row in changed_rows
                        for field in row["json_fields"]["missing"]
                    }
                )
                extra_fields = sorted(
                    {
                        field
                        for row in changed_rows
                        for field in row["json_fields"]["extra"]
                    }
                )
                LOGGER.warning(
                    "数仓 JSON 字段发生变化：source=%s，table=%s，rows=%s，sample_ids=%s，missing=%s，extra=%s",
                    table.source_id,
                    table.table_name,
                    len(changed_rows),
                    [row["id"] for row in changed_rows[:10]],
                    missing_fields,
                    extra_fields,
                )
            datasets[table.source_id] = normalized_rows
            LOGGER.info(
                "竞品来源读取完成：source=%s，table=%s，rows=%s，耗时=%.3fs",
                table.source_id,
                table.table_name,
                len(latest_rows),
                perf_counter() - source_started_at,
            )
    LOGGER.info(
        "五张竞品日数据读取完成：date=%s，耗时=%.3fs",
        selected_date,
        perf_counter() - started_at,
    )
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

    started_at = perf_counter()
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
                    "time_granularity": SELF_SKU_DAY_GRANULARITY,
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
    LOGGER.info(
        "本品 SKU 日数据读取完成：date=%s，rows=%s，耗时=%.3fs",
        selected_date,
        len(result),
        perf_counter() - started_at,
    )
    return result
