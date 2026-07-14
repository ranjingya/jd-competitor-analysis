"""执行区间解析、P 候选、核心约束与置信度计算。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from .sources import clean_text


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricDefinition:
    """定义一个核心指标的标准字段。

    功能说明：统一核心指标 ID、中文字段名和展示单位。
    参数 id：标准指标 ID。
    参数 label：京东导出表中的指标名称。
    参数 unit：网页使用的展示单位。
    返回值：不可变的指标定义对象。
    """

    id: str
    label: str
    unit: str = ""


@dataclass(frozen=True)
class ParsedRange:
    """保存一个已解析的区间值。

    功能说明：保留区间原文、上下界、中位数、百分比和缺失状态。
    参数 raw：原始单元格文本。
    参数 low：区间下界。
    参数 high：区间上界。
    参数 mid：区间中位数。
    参数 is_percent：是否为百分比。
    参数 missing：是否缺失或解析失败。
    返回值：不可变的区间对象。
    """

    raw: str | None
    low: float | None
    high: float | None
    mid: float | None
    is_percent: bool
    missing: bool


CORE_METRICS = (
    MetricDefinition("gmv", "成交金额"),
    MetricDefinition("sold_units", "成交商品件数"),
    MetricDefinition("orders", "成交单量"),
    MetricDefinition("views", "浏览量"),
    MetricDefinition("visitors", "访客数"),
    MetricDefinition("cart_users", "加购人数"),
    MetricDefinition("conversion_rate", "成交转化率", "%"),
    MetricDefinition("customer_price", "成交客单价"),
)

CORE_CARD_IDS = {"gmv", "visitors", "conversion_rate", "customer_price"}
CRITICAL_METRIC_IDS = {"gmv", "visitors", "conversion_rate", "customer_price"}

PHistory = dict[str, list[dict[str, Any]]]


def to_number(value: Any) -> float | None:
    """把真实数值或百分比文本转换为浮点数。"""

    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = clean_text(value).replace(",", "").replace("¥", "").replace("￥", "")
    is_percent = text.endswith("%")
    text = text.rstrip("%")
    multiplier = 10000 if text.endswith("万") else 1
    text = text.rstrip("万")
    try:
        number = float(text) * multiplier
    except ValueError:
        return None
    return number / 100 if is_percent else number


def parse_range(value: Any) -> ParsedRange:
    """把京东区间文本解析为统一数值上下界。"""

    raw = clean_text(value)
    if not raw or raw == "-":
        return ParsedRange(raw or None, None, None, None, False, True)
    is_percent = "%" in raw or "％" in raw
    normalized = raw.replace(",", "").replace("¥", "").replace("￥", "").replace(" ", "").replace("％", "%").replace("%", "")
    parts = re.split(r"~|－|—", normalized)
    parsed = []
    for part in parts:
        if not part:
            continue
        multiplier = 10000 if part.endswith("万") else 1
        try:
            parsed.append(float(part.rstrip("万")) * multiplier / (100 if is_percent else 1))
        except ValueError:
            LOGGER.warning("区间解析失败：%s", raw)
            return ParsedRange(raw, None, None, None, is_percent, True)
    if not parsed:
        return ParsedRange(raw, None, None, None, is_percent, True)
    low = parsed[0]
    high = parsed[1] if len(parsed) > 1 else parsed[0]
    return ParsedRange(raw, low, high, (low + high) / 2, is_percent, False)


def clamp(value: float, interval: ParsedRange) -> float:
    """把数值限制在有效区间内。"""

    if interval.low is None or interval.high is None:
        return value
    return max(interval.low, min(interval.high, value))


def in_range(value: float | None, interval: ParsedRange) -> bool | None:
    """判断数值是否位于区间内。"""

    if value is None or interval.low is None or interval.high is None:
        return None
    return interval.low <= value <= interval.high


def calculate_position_p(actual: float | None, interval: ParsedRange) -> tuple[float | None, bool]:
    """计算本品在行业区间中的原始位置 P。

    功能说明：保留区间外的原始 P，只有真实值位于有效区间内时才允许作为同周期候选。
    参数 actual：本品真实指标值。
    参数 interval：本品行业区间。
    返回值：原始 P 与是否可用于估算的布尔值。
    """

    if actual is None or interval.low is None or interval.high is None:
        return None, False
    if interval.high == interval.low:
        return (0.5, True) if actual == interval.low else (None, False)
    position = (actual - interval.low) / (interval.high - interval.low)
    return position, 0 <= position <= 1


def _candidate_from_p(interval: ParsedRange, position: float | None) -> float | None:
    """把有效 P 映射到目标区间。"""

    if position is None or interval.low is None or interval.high is None:
        return None
    return interval.low + (interval.high - interval.low) * position


def _historical_position(history: PHistory, metric_id: str) -> tuple[float | None, list[str]]:
    """计算同指标历史有效 P 均值及其来源周期。"""

    samples = history.get(metric_id, [])
    values = [float(item["position_p"]) for item in samples if item.get("position_p") is not None]
    periods = [str(item["period_key"]) for item in samples if item.get("position_p") is not None]
    return (fmean(values), periods) if values else (None, [])


def _select_candidate(
    interval: ParsedRange,
    current_p: float | None,
    current_p_valid: bool,
    historical_p: float | None,
) -> tuple[float | None, str]:
    """按当期 P、历史 P、中位值顺序选择候选。"""

    if current_p_valid:
        return _candidate_from_p(interval, current_p), "same_period_p"
    if historical_p is not None:
        return _candidate_from_p(interval, historical_p), "historical_p"
    return interval.mid, "median"


def _nearly_equal(left: float | None, right: float | None) -> bool | None:
    """按相对容差比较两个计算结果。"""

    if left is None or right is None:
        return None
    tolerance = max(1e-6, abs(right) * 1e-6)
    return abs(left - right) <= tolerance


def _top_customer_interval(traffic_rows: list[dict[str, Any]], competitor_prefix: str) -> ParsedRange:
    """提取流量来源顶层成交客户数区间。"""

    for row in traffic_rows:
        if clean_text(row.get("一级渠道")) and not clean_text(row.get("二级渠道")) and not clean_text(row.get("三级渠道")):
            return parse_range(row.get(f"{competitor_prefix}成交客户数"))
    return ParsedRange(None, None, None, None, False, True)


def _solve_constraints(
    candidates: dict[str, float | None],
    ranges: dict[str, ParsedRange],
    traffic_rows: list[dict[str, Any]],
    competitor_prefix: str,
) -> tuple[dict[str, float | None], float | None, dict[str, Any], dict[str, list[str]]]:
    """校正核心指标约束。

    功能说明：在原始竞品区间内依次处理顶层成交客户数、成交公式和件单关系，并记录每个指标的调整原因。
    参数 candidates：各核心指标的首选候选值。
    参数 ranges：各核心指标的竞品原始区间。
    参数 traffic_rows：流量来源原始行。
    参数 competitor_prefix：竞品字段前缀。
    返回值：最终值、竞品成交人数、统一检查结果和按指标归档的调整记录。
    """

    final = dict(candidates)
    adjustments: dict[str, list[str]] = {metric.id: [] for metric in CORE_METRICS}
    conflicts: list[str] = []
    customer_interval = _top_customer_interval(traffic_rows, competitor_prefix)

    visitors = final.get("visitors")
    conversion = final.get("conversion_rate")
    buyers = visitors * conversion if visitors is not None and conversion is not None else None
    if buyers is not None and not customer_interval.missing:
        target_buyers = clamp(buyers, customer_interval)
        if target_buyers != buyers and visitors:
            adjusted_rate = target_buyers / visitors
            if in_range(adjusted_rate, ranges["conversion_rate"]):
                final["conversion_rate"] = adjusted_rate
                conversion = adjusted_rate
                adjustments["conversion_rate"].append("按顶层成交客户数区间校正")
            elif conversion:
                adjusted_visitors = target_buyers / conversion
                if in_range(adjusted_visitors, ranges["visitors"]):
                    final["visitors"] = adjusted_visitors
                    visitors = adjusted_visitors
                    adjustments["visitors"].append("按顶层成交客户数区间校正")
                else:
                    conflicts.append("访客数与成交转化率无法同时满足顶层成交客户数区间")
        buyers = visitors * conversion if visitors is not None and conversion is not None else buyers

    price = final.get("customer_price")
    formula_gmv = buyers * price if buyers is not None and price is not None else None
    if formula_gmv is not None:
        target_gmv = clamp(formula_gmv, ranges["gmv"])
        if buyers:
            adjusted_price = target_gmv / buyers
            if in_range(adjusted_price, ranges["customer_price"]):
                if not _nearly_equal(price, adjusted_price):
                    adjustments["customer_price"].append("按成交金额公式校正")
                final["customer_price"] = adjusted_price
                price = adjusted_price
        final["gmv"] = target_gmv
        if not _nearly_equal(candidates.get("gmv"), target_gmv):
            adjustments["gmv"].append("按成交公式校正并限制在原始区间")
        formula_gmv = buyers * price if buyers is not None and price is not None else None
        if _nearly_equal(formula_gmv, final["gmv"]) is False:
            conflicts.append("成交金额、成交人数与客单价区间无法完全自洽")

    orders = final.get("orders")
    sold_units = final.get("sold_units")
    if orders is not None and sold_units is not None and sold_units < orders:
        adjusted_units = clamp(orders, ranges["sold_units"])
        final["sold_units"] = adjusted_units
        adjustments["sold_units"].append("按不小于成交单量校正")
        if adjusted_units < orders:
            adjusted_orders = clamp(adjusted_units, ranges["orders"])
            final["orders"] = adjusted_orders
            adjustments["orders"].append("按成交商品件数上限校正")
            if adjusted_units < adjusted_orders:
                conflicts.append("成交商品件数与成交单量区间无法满足件单关系")

    for metric in CORE_METRICS:
        value = final.get(metric.id)
        if value is not None:
            bounded = clamp(value, ranges[metric.id])
            if bounded != value:
                adjustments[metric.id].append("限制在竞品原始区间")
                final[metric.id] = bounded

    visitors = final.get("visitors")
    conversion = final.get("conversion_rate")
    buyers = visitors * conversion if visitors is not None and conversion is not None else None
    price = final.get("customer_price")
    formula_gmv = buyers * price if buyers is not None and price is not None else None
    checks = {
        "traffic_consistent": in_range(buyers, customer_interval) if not customer_interval.missing else None,
        "gmv_formula_consistent": _nearly_equal(formula_gmv, final.get("gmv")),
        "units_orders_consistent": (
            final.get("sold_units") >= final.get("orders")
            if final.get("sold_units") is not None and final.get("orders") is not None
            else None
        ),
        "conflicts": conflicts,
    }
    return final, buyers, checks, adjustments


def _metric_confidence(source: str, adjusted: bool, range_consistent: bool | None, conflicts: list[str]) -> str:
    """根据候选来源与约束情况判断单指标置信度。"""

    if source in {"historical_p", "median"} or range_consistent is not True or conflicts:
        return "low"
    if adjusted:
        return "medium"
    return "high"


def _report_confidence(conversions: list[dict[str, Any]], checks: dict[str, Any], validation: list[dict[str, Any]]) -> str:
    """根据关键指标、公式约束和本品区间校验判断报告置信度。"""

    critical = [item for item in conversions if item["metric_id"] in CRITICAL_METRIC_IDS]
    if any(item["confidence"] == "low" for item in critical):
        return "low"
    if checks["gmv_formula_consistent"] is False or checks["traffic_consistent"] is False or checks["conflicts"]:
        return "low"
    if all(item["confidence"] == "high" for item in conversions) and all(item["in_range"] is True for item in validation):
        return "high"
    return "medium"


def analyze_core(normalized: dict[str, Any], history: PHistory | None = None) -> dict[str, Any]:
    """生成核心指标估算与审计结果。

    功能说明：从标准化事实计算当期 P、历史 P、候选值和最终约束结果，并生成可供报告层消费的核心分析对象。
    参数 normalized：单周期标准化事实数据。
    参数 history：同商品、同粒度、此前周期的有效 P 样本，按指标 ID 分组。
    返回值：包含校验、转换、最终值、成交人数、置信度、风险和新增 P 样本的字典。
    """

    history = history or {}
    meta = normalized["meta"]
    self_row = normalized["self_real"]
    core_row = normalized["core_raw"]
    competitor_prefix = meta["competitor_prefix"]
    ranges: dict[str, ParsedRange] = {}
    self_values: dict[str, float | None] = {}
    candidates: dict[str, float | None] = {}
    candidate_sources: dict[str, str] = {}
    validation: list[dict[str, Any]] = []
    candidate_audit: dict[str, dict[str, Any]] = {}
    risks: list[str] = []
    p_samples: list[dict[str, Any]] = []

    LOGGER.info("开始核心估算：%s", meta["period_key"])
    for metric in CORE_METRICS:
        actual = to_number(self_row.get(metric.label))
        self_interval = parse_range(core_row.get(f"本品{metric.label}"))
        competitor_interval = parse_range(core_row.get(f"{competitor_prefix}{metric.label}"))
        current_p, current_p_valid = calculate_position_p(actual, self_interval)
        historical_p, historical_periods = _historical_position(history, metric.id)
        candidate, source = _select_candidate(competitor_interval, current_p, current_p_valid, historical_p)
        median_error = abs(self_interval.mid - actual) / abs(actual) if actual not in {None, 0} and self_interval.mid is not None else None
        historical_self_candidate = _candidate_from_p(self_interval, historical_p)
        historical_error = (
            abs(historical_self_candidate - actual) / abs(actual)
            if actual not in {None, 0} and historical_self_candidate is not None
            else None
        )
        valid = in_range(actual, self_interval)
        validation.append(
            {
                "metric_id": metric.id,
                "metric_label": metric.label,
                "actual_value": actual,
                "range_text": self_interval.raw,
                "range_low": self_interval.low,
                "range_high": self_interval.high,
                "position_p": current_p,
                "position_p_valid": current_p_valid,
                "in_range": valid,
                "median_error_rate": median_error,
                "historical_p": historical_p,
                "historical_p_period": historical_periods[-1] if historical_periods else None,
                "historical_p_periods": historical_periods,
                "historical_p_error_rate": historical_error,
                "note": "本品使用真实 SPU 数据。" if valid else "本品真实值未落入本品区间，当期 P 不参与估算。",
            }
        )
        if valid is False:
            risks.append(f"本品{metric.label}未落入本品区间，当期 P 已停用")
        if source == "historical_p":
            risks.append(f"竞品{metric.label}使用同粒度历史 P 低置信度回退")
        elif source == "median":
            risks.append(f"竞品{metric.label}使用区间中位值低置信度回退")
        if current_p_valid:
            p_samples.append({"metric_id": metric.id, "position_p": current_p, "period_key": meta["period_key"]})
        ranges[metric.id] = competitor_interval
        self_values[metric.id] = actual
        candidates[metric.id] = candidate
        candidate_sources[metric.id] = source
        candidate_audit[metric.id] = {
            "median_candidate": competitor_interval.mid,
            "p_candidate": _candidate_from_p(competitor_interval, current_p) if current_p_valid else None,
            "historical_p_candidate": _candidate_from_p(competitor_interval, historical_p),
            "historical_p": historical_p,
            "historical_p_periods": historical_periods,
        }

    final, buyers, checks, adjustments = _solve_constraints(
        candidates, ranges, normalized["traffic_rows"], competitor_prefix
    )
    conversions = []
    for metric in CORE_METRICS:
        value = final.get(metric.id)
        interval = ranges[metric.id]
        adjusted = bool(adjustments[metric.id])
        confidence = _metric_confidence(
            candidate_sources[metric.id], adjusted, in_range(value, interval), checks["conflicts"]
        )
        basis_labels = {
            "same_period_p": "同周期本品 P 候选",
            "historical_p": "同粒度历史 P 候选",
            "median": "竞品区间中位值兜底",
        }
        conversions.append(
            {
                "metric_id": metric.id,
                "metric_label": metric.label,
                "range_text": interval.raw,
                "range_low": interval.low,
                "range_high": interval.high,
                **candidate_audit[metric.id],
                "candidate_source": candidate_sources[metric.id],
                "selected_candidate": candidates[metric.id],
                "final_value": value,
                "basis": "；".join([basis_labels[candidate_sources[metric.id]], *adjustments[metric.id]]),
                "confidence": confidence,
                "checks": {
                    "range_consistent": in_range(value, interval),
                    "traffic_consistent": checks["traffic_consistent"],
                    "gmv_formula_consistent": checks["gmv_formula_consistent"],
                    "units_orders_consistent": checks["units_orders_consistent"],
                    "adjustments": adjustments[metric.id],
                    "conflicts": checks["conflicts"],
                },
            }
        )

    report_confidence = _report_confidence(conversions, checks, validation)
    if checks["conflicts"]:
        risks.extend(checks["conflicts"])
    LOGGER.info("核心估算完成：%s，置信度=%s", meta["period_key"], report_confidence)
    return {
        "validation": validation,
        "conversions": conversions,
        "self_values": self_values,
        "final_values": final,
        "competitor_buyers": buyers,
        "checks": checks,
        "report_confidence": report_confidence,
        "risks": list(dict.fromkeys(risks)),
        "p_samples": p_samples,
    }
