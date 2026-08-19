"""把数仓竞品日数据转换为固定字段的标准化事实。"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Callable, Iterable

from .sources import clean_identifier, clean_text
from .warehouse_sources import COMPETITOR_TABLES, ProductPair, parse_report_date


LOGGER = logging.getLogger(__name__)

METRIC_STATUSES = {"range", "exact", "masked", "invalid"}
PROFILE_DIMENSIONS = {
    "性别": "gender",
    "年龄": "age",
    "地区": "region",
    "省份": "province",
    "城市": "city",
}
SOURCE_TABLES = {item.source_id: item.table_name for item in COMPETITOR_TABLES}

CORE_METRICS = (
    ("page_views", "浏览量", "count"),
    ("visitors", "访客数", "count"),
    ("add_to_cart_users", "加购人数", "count"),
    ("orders", "成交单量", "count"),
    ("units_sold", "成交商品件数", "count"),
    ("gmv", "成交金额", "currency"),
    ("conversion_rate", "成交转化率", "ratio"),
    ("average_order_value", "成交客单价", "currency"),
    ("search_clicks", "搜索点击次数", "count"),
)
TRAFFIC_METRICS = (
    ("visitors", "访客数", "count"),
    ("visitor_share", "访客数占比", "ratio"),
    ("gmv", "成交金额", "currency"),
    ("conversion_rate", "成交转化率", "ratio"),
    ("buyers", "成交客户数", "count"),
)

Normalizer = Callable[[list[dict[str, Any]]], dict[str, Any]]


def _compact_number(value: float) -> int | float:
    """将整数浮点值压缩为整数，保持 JSON 易读。"""

    return int(value) if value.is_integer() else value


def _parse_number(part: str, is_ratio: bool) -> int | float | None:
    """解析区间中的单个数值端点。"""

    normalized = part.strip()
    multiplier = 10000 if normalized.endswith("万") else 1
    normalized = normalized.rstrip("万")
    try:
        value = float(normalized) * multiplier
    except ValueError:
        return None
    if is_ratio:
        value /= 100
    if not math.isfinite(value):
        return None
    return _compact_number(value)


def normalize_metric(value: Any, unit: str) -> dict[str, Any]:
    """将一个区间或单值转换为固定指标结构。

    功能说明：解析货币、数量、百分比和“万”单位；字段不存在、空值及 `-` 统一标记为 `masked`。
    参数 value：数仓 JSON 中的原始字段值。
    参数 unit：标准单位，使用 `count`、`currency` 或 `ratio`。
    返回值：包含 `raw`、`status`、`low`、`high`、`unit` 的指标对象。
    """

    raw = None if value is None else clean_text(value)
    if not raw or raw == "-":
        return {"raw": raw, "status": "masked", "low": None, "high": None, "unit": unit}

    is_ratio = unit == "ratio"
    normalized = (
        raw.replace(",", "")
        .replace("¥", "")
        .replace("￥", "")
        .replace("％", "%")
        .replace("%", "")
        .replace(" ", "")
    )
    parts = [part for part in re.split(r"~|～|－|—|–|至", normalized) if part]
    values = [_parse_number(part, is_ratio) for part in parts]
    if not values or len(values) > 2 or any(item is None for item in values):
        LOGGER.warning("指标值解析失败：raw=%s，unit=%s", raw, unit)
        return {"raw": raw, "status": "invalid", "low": None, "high": None, "unit": unit}

    low = values[0]
    high = values[-1]
    if low is None or high is None or low > high:
        LOGGER.warning("指标区间上下界无效：raw=%s，unit=%s", raw, unit)
        return {"raw": raw, "status": "invalid", "low": None, "high": None, "unit": unit}
    status = "exact" if len(values) == 1 else "range"
    return {"raw": raw, "status": status, "low": low, "high": high, "unit": unit}


def _normalize_side(data: dict[str, Any], prefix: str, definitions: Iterable[tuple[str, str, str]]) -> dict[str, Any]:
    """按字段定义转换本品或竞品的一组指标。"""

    return {
        metric_id: normalize_metric(data.get(f"{prefix}{source_label}"), unit)
        for metric_id, source_label, unit in definitions
    }


def _source_metadata(source_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """提取来源表、同步时间和原始行号。"""

    timestamps = [clean_text(row.get("updated_at")) for row in rows if row.get("updated_at") is not None]
    return {
        "table": SOURCE_TABLES[source_id],
        "updated_at": max(timestamps) if timestamps else None,
        "row_ids": [row.get("id") for row in rows if row.get("id") is not None],
        "row_count": len(rows),
    }


def _metric_objects(value: Any) -> Iterable[dict[str, Any]]:
    """递归枚举记录中的固定指标对象。"""

    if isinstance(value, dict):
        if set(value) == {"raw", "status", "low", "high", "unit"} and value.get("status") in METRIC_STATUSES:
            yield value
            return
        for child in value.values():
            yield from _metric_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _metric_objects(child)


def _quality(records: list[dict[str, Any]], extra_issues: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """按记录和指标状态生成来源质量结果。"""

    issues = list(extra_issues or [])
    if not records:
        issues.append({"code": "no_records", "message": "当天没有可用记录"})
        return {"status": "unavailable", "issues": issues}

    metrics = list(_metric_objects(records))
    if not metrics:
        issues.append({"code": "no_metrics", "message": "记录中没有可用指标字段"})
        return {"status": "unavailable", "issues": issues}

    invalid_count = sum(item["status"] == "invalid" for item in metrics)
    masked_count = sum(item["status"] == "masked" for item in metrics)
    usable_count = len(metrics) - invalid_count - masked_count
    if usable_count == 0:
        issues.append({"code": "all_metrics_unavailable", "message": "来源中的指标均不可用"})
        status = "unavailable"
    elif invalid_count or masked_count or issues:
        status = "partial"
    else:
        status = "ready"
    if invalid_count:
        issues.append({"code": "invalid_metrics", "message": f"有 {invalid_count} 个指标无法解析"})
    if masked_count:
        issues.append({"code": "masked_metrics", "message": f"有 {masked_count} 个指标未披露"})
    return {"status": status, "issues": issues}


def _wrap_source(
    source_id: str,
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    issues: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """组装统一的来源、记录和质量外层。"""

    return {
        "source": _source_metadata(source_id, rows),
        "records": records,
        "quality": _quality(records, issues),
    }


def normalize_core_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """转换竞品核心指标来源。

    功能说明：将每条核心对比数据拆成本品和目标竞品两侧的固定英文指标结构。
    参数 rows：`read_competitor_sources` 返回的核心指标原始行。
    返回值：包含来源信息、标准化记录和质量状态的核心指标对象。
    """

    LOGGER.info("开始标准化核心指标：rows=%s", len(rows))
    records = []
    for row in rows:
        data = row.get("data") or {}
        records.append(
            {
                "self": _normalize_side(data, "本品", CORE_METRICS),
                "competitor": _normalize_side(data, "竞品1", CORE_METRICS),
            }
        )
    issues = []
    if len(records) > 1:
        issues.append({"code": "multiple_core_records", "message": "核心指标应只有一条记录"})
    result = _wrap_source("core_metrics", rows, records, issues)
    LOGGER.info("核心指标标准化完成：records=%s，status=%s", len(records), result["quality"]["status"])
    return result


def _channel_name(value: Any) -> str | None:
    """将空渠道和 `-` 转换为 null。"""

    text = clean_text(value)
    return text if text and text != "-" else None


def normalize_traffic_sources(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """转换流量来源明细。

    功能说明：保留三级渠道层级，并将两侧访客、占比、成交和转化字段转换为固定结构。
    参数 rows：`read_competitor_sources` 返回的流量来源原始行。
    返回值：包含来源信息、标准化渠道记录和质量状态的流量来源对象。
    """

    LOGGER.info("开始标准化流量来源：rows=%s", len(rows))
    records = []
    for row in rows:
        data = row.get("data") or {}
        levels = [_channel_name(data.get(key)) for key in ("一级渠道", "二级渠道", "三级渠道")]
        records.append(
            {
                "channel_level_1": levels[0],
                "channel_level_2": levels[1],
                "channel_level_3": levels[2],
                "channel_path": " > ".join(level for level in levels if level),
                "self": _normalize_side(data, "本品", TRAFFIC_METRICS),
                "competitor": _normalize_side(data, "竞品1", TRAFFIC_METRICS),
            }
        )
    result = _wrap_source("traffic_sources", rows, records)
    LOGGER.info("流量来源标准化完成：records=%s，status=%s", len(records), result["quality"]["status"])
    return result


def normalize_traffic_keywords(rows: list[dict[str, Any]], product_pair: ProductPair) -> dict[str, Any]:
    """转换引流关键词明细。

    功能说明：按 SPU 标记本品或竞品，并固定输出商品、关键词、访客数和成交金额字段。
    参数 rows：`read_competitor_sources` 返回的关键词原始行。
    参数 product_pair：当前本品与竞品 SPU 商品对。
    返回值：包含来源信息、标准化关键词记录和质量状态的关键词对象。
    """

    LOGGER.info("开始标准化引流关键词：rows=%s", len(rows))
    records = []
    issues: list[dict[str, str]] = []
    for row in rows:
        data = row.get("data") or {}
        spu_id = clean_identifier(data.get("SPUID"))
        if spu_id == product_pair.self_spu:
            product_role = "self"
        elif spu_id == product_pair.competitor_spu:
            product_role = "competitor"
        else:
            issues.append({"code": "unexpected_keyword_spu", "message": f"关键词记录包含商品对之外的 SPU：{spu_id or '空'}"})
            continue
        records.append(
            {
                "product_role": product_role,
                "spu_id": spu_id,
                "product_name": clean_text(data.get("商品名称")) or None,
                "keyword": clean_text(data.get("关键词")) or None,
                "visitors": normalize_metric(data.get("访客数"), "count"),
                "gmv": normalize_metric(data.get("成交金额"), "currency"),
            }
        )
    result = _wrap_source("traffic_keywords", rows, records, issues)
    LOGGER.info("引流关键词标准化完成：records=%s，status=%s", len(records), result["quality"]["status"])
    return result


def _infer_profile_dimension(segment: str) -> str | None:
    """在缺少标题行时按画像项名称推断维度。"""

    if "岁" in segment or re.search(r"\d+\s*[-~至]\s*\d+", segment):
        return "age"
    if segment in {"男", "女", "男性", "女性", "未知"}:
        return "gender"
    if segment.endswith(("省", "自治区", "特别行政区")):
        return "province"
    if segment.endswith(("市", "州", "地区", "盟")):
        return "city"
    return None


def normalize_customer_profiles(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """转换成交客户画像明细。

    功能说明：按原始行顺序识别画像维度标题，为每个画像项固定补齐两侧占比字段。
    参数 rows：`read_competitor_sources` 返回且按原始 `id` 升序排列的画像原始行。
    返回值：包含来源信息、标准化画像记录和质量状态的画像对象。
    """

    LOGGER.info("开始标准化客户画像：rows=%s", len(rows))
    records = []
    issues: list[dict[str, str]] = []
    current_dimension: str | None = None
    for row in rows:
        data = row.get("data") or {}
        segment = clean_text(data.get("画像类型"))
        if not segment:
            issues.append({"code": "missing_profile_segment", "message": "画像记录缺少画像类型"})
            continue
        if segment in PROFILE_DIMENSIONS:
            current_dimension = PROFILE_DIMENSIONS[segment]
            continue
        dimension = current_dimension or _infer_profile_dimension(segment)
        if dimension is None:
            dimension = "unknown"
            issues.append({"code": "unknown_profile_dimension", "message": f"无法识别画像项所属维度：{segment}"})
        records.append(
            {
                "dimension": dimension,
                "segment": segment,
                "self_share": normalize_metric(data.get("本品成交客户数占比"), "ratio"),
                "competitor_share": normalize_metric(data.get("竞品1成交客户数占比"), "ratio"),
            }
        )
    result = _wrap_source("customer_profiles", rows, records, issues)
    LOGGER.info("客户画像标准化完成：records=%s，status=%s", len(records), result["quality"]["status"])
    return result


def _promotion_side(data: dict[str, Any], prefix: str) -> dict[str, Any]:
    """转换推广数据的一侧指标。"""

    return {
        "full_site": {
            "gmv": normalize_metric(data.get(f"全站-{prefix}全站交易额"), "currency"),
            "core_position_clicks": normalize_metric(data.get(f"全站-{prefix}核心位置点击数"), "count"),
        },
        "non_full_site": {
            "ad_clicks": normalize_metric(data.get(f"非全站-{prefix}广告点击数"), "count"),
            "ad_order_gmv": normalize_metric(data.get(f"非全站-{prefix}广告总订单金额"), "currency"),
        },
    }


def normalize_promotion(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """转换推广和广告数据。

    功能说明：固定输出全站交易、核心位置点击、非全站广告点击和广告订单金额。
    参数 rows：`read_competitor_sources` 返回的推广原始行。
    返回值：包含来源信息、标准化推广记录和质量状态的推广对象。
    """

    LOGGER.info("开始标准化推广数据：rows=%s", len(rows))
    records = []
    for row in rows:
        data = row.get("data") or {}
        records.append(
            {
                "self": _promotion_side(data, "本店商品"),
                "competitor": _promotion_side(data, "竞品1"),
            }
        )
    result = _wrap_source("promotion", rows, records)
    LOGGER.info("推广数据标准化完成：records=%s，status=%s", len(records), result["quality"]["status"])
    return result


def normalize_competitor_sources(
    raw_sources: dict[str, list[dict[str, Any]]],
    product_pair: ProductPair,
    report_date: str,
) -> dict[str, Any]:
    """统一转换五张竞品来源表。

    功能说明：校验日维度参数，调用五类转换器，并生成商品对、来源模块和整体质量摘要。
    参数 raw_sources：按五个来源 ID 分组的数仓原始记录。
    参数 product_pair：当前本品与竞品 SPU 商品对。
    参数 report_date：业务日期，格式为 `YYYY-MM-DD`。
    返回值：可写入日数据集 `payload_json` 的竞品事实部分。
    """

    selected_date = parse_report_date(report_date).isoformat()
    LOGGER.info("开始标准化五张竞品表：date=%s，compare_number=%s", selected_date, product_pair.compare_number)
    normalizers: dict[str, Normalizer] = {
        "core_metrics": normalize_core_metrics,
        "traffic_sources": normalize_traffic_sources,
        "customer_profiles": normalize_customer_profiles,
        "promotion": normalize_promotion,
    }
    sources = {
        source_id: (
            normalize_traffic_keywords(raw_sources.get(source_id, []), product_pair)
            if source_id == "traffic_keywords"
            else normalizers[source_id](raw_sources.get(source_id, []))
        )
        for source_id in SOURCE_TABLES
    }
    source_statuses = [source["quality"]["status"] for source in sources.values()]
    core_status = sources["core_metrics"]["quality"]["status"]
    if core_status == "unavailable":
        overall_status = "invalid"
    elif all(status == "ready" for status in source_statuses):
        overall_status = "ready"
    else:
        overall_status = "partial"
    issues = [
        {"source": source_id, **issue}
        for source_id, source in sources.items()
        for issue in source["quality"]["issues"]
    ]
    result = {
        "schema_version": "2.0",
        "report_date": selected_date,
        "pair": {
            "compare_number": product_pair.compare_number,
            "self_spu": product_pair.self_spu,
            "competitor_spu": product_pair.competitor_spu,
        },
        "sources": sources,
        "quality": {"status": overall_status, "issues": issues},
    }
    LOGGER.info("五张竞品表标准化完成：date=%s，status=%s", selected_date, overall_status)
    return result
