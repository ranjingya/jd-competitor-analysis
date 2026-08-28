"""把已完成日报聚合为周报或月报基础报告。"""

from __future__ import annotations

import copy
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Iterable

from .report import build_core_views, build_tabs
from .time_utils import beijing_now_text


SUM_CORE_METRICS = ("gmv", "sold_units", "orders", "views", "visitors", "cart_users")


def _number(value: Any) -> float | None:
    """把可用数值转换为浮点数。"""

    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_values(values: Iterable[Any]) -> float | None:
    """累加非空数值；全部为空时返回空值。"""

    numbers = [number for value in values if (number := _number(value)) is not None]
    return sum(numbers) if numbers else None


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    """执行安全除法。"""

    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def _weighted_average(
    entries: Iterable[dict[str, Any]],
    value_key: str,
    weight_key: str,
) -> float | None:
    """按可用分母对比例执行加权平均。"""

    numerator = 0.0
    denominator = 0.0
    for entry in entries:
        value = _number(entry.get(value_key))
        weight = _number(entry.get(weight_key))
        if value is None or weight is None or weight <= 0:
            continue
        numerator += value * weight
        denominator += weight
    return numerator / denominator if denominator else None


def _difference(left: float | None, right: float | None) -> float | None:
    """计算两侧差值；任一侧缺失时返回空值。"""

    return left - right if left is not None and right is not None else None


def _difference_with_missing(left: float | None, right: float | None) -> float:
    """计算允许单侧缺失的差值，缺失侧仅在差值中按零处理。"""

    return (left or 0.0) - (right or 0.0)


def _judgement(left: float | None, right: float | None) -> str:
    """根据两侧可用值生成统一判断。"""

    if left is None or right is None:
        return "无完整口径"
    if left > right:
        return "本品领先"
    if left < right:
        return "本品落后"
    return "基本持平"


def _report_comparison(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """把日报核心对比转换为指标 ID 索引。"""

    return {
        str(item.get("metric_id")): item
        for item in report.get("comparison", [])
        if isinstance(item, dict) and item.get("metric_id")
    }


def _aggregate_core(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """聚合核心指标并重新计算转化率和客单价。"""

    comparisons = [_report_comparison(row["report"]) for row in rows]
    self_values = {
        metric_id: _sum_values(
            comparison.get(metric_id, {}).get("self_value") for comparison in comparisons
        )
        for metric_id in SUM_CORE_METRICS
    }
    competitor_values = {
        metric_id: _sum_values(
            comparison.get(metric_id, {}).get("competitor_value") for comparison in comparisons
        )
        for metric_id in SUM_CORE_METRICS
    }
    self_buyers = _sum_values(row.get("self_buyers") for row in rows)
    competitor_buyers = _sum_values(row.get("competitor_buyers") for row in rows)
    self_values["conversion_rate"] = _divide(self_buyers, self_values["visitors"])
    competitor_values["conversion_rate"] = _divide(
        competitor_buyers, competitor_values["visitors"]
    )
    self_values["customer_price"] = _divide(self_values["gmv"], self_buyers)
    competitor_values["customer_price"] = _divide(
        competitor_values["gmv"], competitor_buyers
    )
    return build_core_views(
        {"self_values": self_values, "final_values": competitor_values}
    )


def _aggregate_traffic(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按渠道路径汇总流量来源并重算占比与转化率。"""

    grouped: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        report = row["report"]
        daily_core = _report_comparison(report)
        daily_traffic = {
            (item.get("level_1"), item.get("level_2"), item.get("level_3")): item
            for item in report.get("traffic_sources", [])
            if isinstance(item, dict)
        }
        for key, item in daily_traffic.items():
            if isinstance(item, dict):
                level_1, level_2, level_3 = key
                parent_key = (
                    (level_1, level_2, None)
                    if level_3 is not None
                    else (level_1, None, None) if level_2 is not None else None
                )
                parent = daily_traffic.get(parent_key) if parent_key is not None else None
                grouped[key].append(
                    {
                        "item": item,
                        "self_total_weight": daily_core.get("visitors", {}).get("self_value"),
                        "competitor_total_weight": daily_core.get("visitors", {}).get(
                            "competitor_value"
                        ),
                        "self_current_weight": (
                            parent.get("self_visitors")
                            if parent is not None
                            else daily_core.get("visitors", {}).get("self_value")
                        ),
                        "competitor_current_weight": (
                            parent.get("competitor_visitors")
                            if parent is not None
                            else daily_core.get("visitors", {}).get("competitor_value")
                        ),
                        "self_total_rate": item.get("self_total_visitor_rate"),
                        "competitor_total_rate": item.get("competitor_total_visitor_rate"),
                        "self_current_rate": item.get("self_current_level_visitor_rate"),
                        "competitor_current_rate": item.get(
                            "competitor_current_level_visitor_rate"
                        ),
                    }
                )
    aggregated: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for key, entries in grouped.items():
        items = [entry["item"] for entry in entries]
        level_1, level_2, level_3 = key
        self_visitors = _sum_values(item.get("self_visitors") for item in items)
        competitor_visitors = _sum_values(item.get("competitor_visitors") for item in items)
        self_customers = _sum_values(item.get("self_customers") for item in items)
        competitor_customers = _sum_values(item.get("competitor_customers") for item in items)
        self_gmv = _sum_values(item.get("self_gmv") for item in items)
        competitor_gmv = _sum_values(item.get("competitor_gmv") for item in items)
        aggregated[key] = {
            "level_1": level_1,
            "level_2": level_2,
            "level_3": level_3,
            "path": " > ".join(str(value) for value in key if value),
            "self_visitors": self_visitors,
            "competitor_visitors": competitor_visitors,
            "self_customers": self_customers,
            "competitor_customers": competitor_customers,
            "self_gmv": self_gmv,
            "competitor_gmv": competitor_gmv,
            "self_conversion_rate": _divide(self_customers, self_visitors),
            "competitor_conversion_rate": _divide(competitor_customers, competitor_visitors),
            "visitor_gap": _difference_with_missing(self_visitors, competitor_visitors),
            "gmv_gap": _difference_with_missing(self_gmv, competitor_gmv),
            "conversion_gap_pct": None,
            "self_total_visitor_rate": _weighted_average(
                entries, "self_total_rate", "self_total_weight"
            ),
            "competitor_total_visitor_rate": _weighted_average(
                entries, "competitor_total_rate", "competitor_total_weight"
            ),
            "self_visitor_rate": _weighted_average(
                entries, "self_total_rate", "self_total_weight"
            ),
            "competitor_visitor_rate": _weighted_average(
                entries, "competitor_total_rate", "competitor_total_weight"
            ),
            "self_current_level_visitor_rate": _weighted_average(
                entries, "self_current_rate", "self_current_weight"
            ),
            "competitor_current_level_visitor_rate": _weighted_average(
                entries, "competitor_current_rate", "competitor_current_weight"
            ),
            "judgement": _judgement(self_visitors, competitor_visitors),
            "estimation_basis": "由可用日报汇总",
        }
    for item in aggregated.values():
        self_conversion = item["self_conversion_rate"]
        competitor_conversion = item["competitor_conversion_rate"]
        item["conversion_gap_pct"] = (
            (self_conversion - competitor_conversion) * 100
            if self_conversion is not None and competitor_conversion is not None
            else None
        )
    return sorted(aggregated.values(), key=lambda item: item["path"])


def _aggregate_keywords(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """按关键词汇总访客和成交金额并重算覆盖率。"""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    coverage_entries: list[dict[str, Any]] = []
    notes: list[str] = []
    for row in rows:
        report = row["report"]
        module = report.get("keywords", {})
        daily_core = _report_comparison(report)
        coverage = module.get("coverage", {})
        coverage_entries.append(
            {
                "self_visitor_rate": coverage.get("self_visitor_rate"),
                "competitor_visitor_rate": coverage.get("competitor_visitor_rate"),
                "self_gmv_rate": coverage.get("self_gmv_rate"),
                "competitor_gmv_rate": coverage.get("competitor_gmv_rate"),
                "self_visitors": daily_core.get("visitors", {}).get("self_value"),
                "competitor_visitors": daily_core.get("visitors", {}).get(
                    "competitor_value"
                ),
                "self_gmv": daily_core.get("gmv", {}).get("self_value"),
                "competitor_gmv": daily_core.get("gmv", {}).get("competitor_value"),
            }
        )
        notes.extend(str(note) for note in module.get("notes", []) if note not in notes)
        for item in module.get("rows", []):
            if isinstance(item, dict) and item.get("keyword"):
                grouped[str(item["keyword"])].append(
                    {
                        "item": item,
                        "self_weight": daily_core.get("visitors", {}).get("self_value"),
                        "competitor_weight": daily_core.get("visitors", {}).get(
                            "competitor_value"
                        ),
                        "self_share": item.get("self_visitor_share"),
                        "competitor_share": item.get("competitor_visitor_share"),
                    }
                )
    result_rows = []
    for keyword, entries in grouped.items():
        items = [entry["item"] for entry in entries]
        self_visitors = _sum_values(item.get("self_visitors") for item in items)
        competitor_visitors = _sum_values(item.get("competitor_visitors") for item in items)
        self_gmv = _sum_values(item.get("self_gmv") for item in items)
        competitor_gmv = _sum_values(item.get("competitor_gmv") for item in items)
        if self_visitors is None:
            relation = "竞品独有"
        elif competitor_visitors is None:
            relation = "本品独有"
        else:
            relation = "共同词"
        visitor_gap = _difference_with_missing(self_visitors, competitor_visitors)
        gmv_gap = _difference_with_missing(self_gmv, competitor_gmv)
        if relation == "竞品独有":
            opportunity = "补词机会"
        elif visitor_gap is not None and visitor_gap < 0:
            opportunity = "访客落后"
        elif gmv_gap is not None and gmv_gap < 0:
            opportunity = "成交落后"
        elif relation == "本品独有":
            opportunity = "保持优势"
        else:
            opportunity = "本品领先"
        result_rows.append(
            {
                "keyword": keyword,
                "self_visitors": self_visitors,
                "competitor_visitors": competitor_visitors,
                "self_gmv": self_gmv,
                "competitor_gmv": competitor_gmv,
                "visitor_gap": visitor_gap,
                "gmv_gap": gmv_gap,
                "coverage_relation": relation,
                "opportunity": opportunity,
                "self_visitor_share": _weighted_average(
                    entries, "self_share", "self_weight"
                ),
                "competitor_visitor_share": _weighted_average(
                    entries, "competitor_share", "competitor_weight"
                ),
            }
        )
    result_rows.sort(
        key=lambda item: abs(item["visitor_gap"] or 0) + abs(item["gmv_gap"] or 0),
        reverse=True,
    )
    return {
        "rows": result_rows,
        "coverage": {
            "self_visitor_rate": _weighted_average(
                coverage_entries, "self_visitor_rate", "self_visitors"
            ),
            "competitor_visitor_rate": _weighted_average(
                coverage_entries, "competitor_visitor_rate", "competitor_visitors"
            ),
            "self_gmv_rate": _weighted_average(
                coverage_entries, "self_gmv_rate", "self_gmv"
            ),
            "competitor_gmv_rate": _weighted_average(
                coverage_entries, "competitor_gmv_rate", "competitor_gmv"
            ),
        },
        "notes": notes or ["关键词列表为 Top 口径，合计不代表商品全量。"],
    }


def _aggregate_profile(rows: list[dict[str, Any]], comparison: list[dict[str, Any]]) -> dict[str, Any]:
    """按画像维度与取值汇总估算客户数并重算占比。"""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    notes: list[str] = []
    for row in rows:
        module = row["report"].get("customer_profile", {})
        notes.extend(str(note) for note in module.get("notes", []) if note not in notes)
        for dimension in module.get("dimensions", []):
            for item in dimension.get("items", []):
                if isinstance(item, dict) and item.get("name"):
                    grouped[(str(dimension.get("dimension")), str(item["name"]))].append(item)
    core = {str(item["metric_id"]): item for item in comparison}
    self_visitors = _number(core.get("visitors", {}).get("self_value"))
    competitor_visitors = _number(core.get("visitors", {}).get("competitor_value"))
    self_conversion = _number(core.get("conversion_rate", {}).get("self_value"))
    competitor_conversion = _number(core.get("conversion_rate", {}).get("competitor_value"))
    self_buyers = self_visitors * self_conversion if self_visitors is not None and self_conversion is not None else None
    competitor_buyers = (
        competitor_visitors * competitor_conversion
        if competitor_visitors is not None and competitor_conversion is not None
        else None
    )
    dimensions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (dimension, name), items in grouped.items():
        self_customers = _sum_values(item.get("self_estimated_customers") for item in items)
        competitor_customers = _sum_values(
            item.get("competitor_estimated_customers") for item in items
        )
        self_rate_fraction = _divide(self_customers, self_buyers)
        competitor_rate_fraction = _divide(competitor_customers, competitor_buyers)
        self_rate = self_rate_fraction * 100 if self_rate_fraction is not None else None
        competitor_rate = (
            competitor_rate_fraction * 100 if competitor_rate_fraction is not None else None
        )
        dimensions[dimension].append(
            {
                "dimension": dimension,
                "name": name,
                "self_rate": self_rate,
                "competitor_rate": competitor_rate,
                "gap_rate": _difference(self_rate, competitor_rate),
                "self_estimated_customers": self_customers,
                "competitor_estimated_customers": competitor_customers,
                "judgement": _judgement(self_rate, competitor_rate),
            }
        )
    return {
        "dimensions": [
            {"dimension": dimension, "items": items}
            for dimension, items in sorted(dimensions.items())
        ],
        "notes": notes or ["各画像维度分别比较；缺失值不等同于 0。"],
    }


def _aggregate_promotion(rows: list[dict[str, Any]], comparison: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总推广点击与归因成交金额。"""

    modules = [row["report"].get("promotion", {}) for row in rows]
    self_clicks = _sum_values(module.get("self", {}).get("ad_clicks") for module in modules)
    competitor_clicks = _sum_values(
        module.get("competitor", {}).get("ad_clicks") for module in modules
    )
    self_gmv = _sum_values(module.get("self", {}).get("ad_order_gmv") for module in modules)
    competitor_gmv = _sum_values(
        module.get("competitor", {}).get("ad_order_gmv") for module in modules
    )
    core = {str(item["metric_id"]): item for item in comparison}
    competitor_core_gmv = _number(core.get("gmv", {}).get("competitor_value"))
    return {
        "available": any(module.get("available") for module in modules),
        "self": {"ad_clicks": self_clicks, "ad_order_gmv": self_gmv},
        "competitor": {
            "ad_clicks": competitor_clicks,
            "ad_order_gmv": competitor_gmv,
        },
        "attributed_gmv_rate": _divide(competitor_gmv, competitor_core_gmv),
        "judgement": _judgement(self_gmv, competitor_gmv),
        "notes": ["推广成交为广告归因口径，不与核心 SPU 成交金额强制对齐。"],
    }


def _calendar_dates(start_date: str, end_date: str) -> list[str]:
    """生成包含首尾日期的自然日列表。"""

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("周期结束日期不能早于开始日期")
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]


def aggregate_period_report(
    daily_rows: list[dict[str, Any]],
    granularity: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """把一个商品对的已完成日报聚合为周期基础报告。

    功能说明：金额、人数和次数按日累加；转化率按成交人数除以访客数重算；
    客单价按成交金额除以成交人数重算；占比按周期分子分母重算。缺失日报不会
    阻止生成报告，日均值始终使用自然周期天数。
    参数 daily_rows：同一商品对在周期内的已完成日报及数据库数值字段。
    参数 granularity：报告粒度，只允许 week 或 month。
    参数 start_date：周期开始日期。
    参数 end_date：周期结束日期。
    返回值：可直接持久化并提交 AI 分析的周期基础报告。
    """

    if granularity not in {"week", "month"}:
        raise ValueError("周期聚合粒度必须为 week 或 month")
    if not daily_rows:
        raise ValueError("周期内没有可聚合的已完成日报")
    pair_keys = {(row["self_spu"], row["competitor_spu"]) for row in daily_rows}
    if len(pair_keys) != 1:
        raise ValueError("一次周期聚合只能包含一个商品对")
    expected_dates = _calendar_dates(start_date, end_date)
    available_dates = sorted({str(row["report_date"]) for row in daily_rows})
    missing_dates = [value for value in expected_dates if value not in available_dates]
    first_report = daily_rows[0]["report"]
    comparison, core_metrics = _aggregate_core(daily_rows)
    traffic = _aggregate_traffic(daily_rows)
    keywords = _aggregate_keywords(daily_rows)
    profile = _aggregate_profile(daily_rows, comparison)
    promotion = _aggregate_promotion(daily_rows, comparison)
    self_spu, competitor_spu = next(iter(pair_keys))
    report = copy.deepcopy(first_report)
    report["comparison"] = comparison
    report["core_metrics"] = core_metrics
    report["traffic_sources"] = traffic
    report["keywords"] = keywords
    report["customer_profile"] = profile
    report["promotion"] = promotion
    report["tabs"] = build_tabs(traffic, keywords, profile)
    report["ai_findings"] = []
    report["ai_recommendations"] = []
    report["quality_status"] = "partial" if missing_dates else "ready"
    source_risks = []
    for row in daily_rows:
        for risk in row["report"].get("risks", []):
            if isinstance(risk, str) and risk not in source_risks:
                source_risks.append(risk)
    period_risks = [
        f"周期内缺少 {len(missing_dates)} 天日报：{', '.join(missing_dates)}"
    ] if missing_dates else []
    report["risks"] = [*period_risks, *source_risks]
    meta = report["meta"]
    meta.update(
        {
            "period": f"{start_date} 至 {end_date}",
            "period_start": start_date,
            "period_end": end_date,
            "period_key": f"{granularity}:{start_date}:{end_date}",
            "granularity": granularity,
            "self_spu": self_spu,
            "competitor_spu": competitor_spu,
            "summary": "等待 AI 生成周期优势摘要",
            "summary_detail": [],
            "weakness_summary": "等待 AI 生成周期弱点摘要",
            "weakness_summary_detail": [],
            "source_report_ids": [row["report_id"] for row in daily_rows],
            "period_days": len(expected_dates),
            "available_days": len(available_dates),
            "missing_days": missing_dates,
            "daily_averages": {
                metric_id: {
                    "self_value": _divide(_number(item.get("self_value")), len(expected_dates)),
                    "competitor_value": _divide(
                        _number(item.get("competitor_value")), len(expected_dates)
                    ),
                }
                for metric_id, item in {
                    str(item["metric_id"]): item for item in comparison
                }.items()
                if metric_id in SUM_CORE_METRICS
            },
            "generated_at": beijing_now_text(),
        }
    )
    return report


def build_period_ai_payload(report: dict[str, Any]) -> dict[str, Any]:
    """从周期基础报告生成精简 AI 输入。

    功能说明：仅发送周期、商品对、核心指标和四个来源模块，不发送页面 tabs、
    日报 AI 文案或审计信息。
    参数 report：已经完成确定性周期聚合的基础报告。
    返回值：供 DeepSeek 分析器读取的周期业务事实。
    """

    meta = report["meta"]
    return {
        "period": {
            "granularity": meta["granularity"],
            "start_date": meta["period_start"],
            "end_date": meta["period_end"],
            "period_days": meta["period_days"],
            "available_days": meta["available_days"],
            "missing_days": copy.deepcopy(meta["missing_days"]),
        },
        "pair": {
            "self_spu": meta["self_spu"],
            "competitor_spu": meta["competitor_spu"],
        },
        "self_spu_data": {
            "spu_id": meta["self_spu"],
            "metrics": {
                str(item["metric_id"]): item.get("self_value")
                for item in report["comparison"]
            },
            "daily_averages": copy.deepcopy(meta["daily_averages"]),
        },
        "tables": {
            "core_metrics": copy.deepcopy(report["comparison"]),
            "traffic_sources": copy.deepcopy(report["traffic_sources"]),
            "traffic_keywords": copy.deepcopy(report["keywords"]),
            "customer_profiles": copy.deepcopy(report["customer_profile"]),
            "promotion": copy.deepcopy(report["promotion"]),
        },
    }
