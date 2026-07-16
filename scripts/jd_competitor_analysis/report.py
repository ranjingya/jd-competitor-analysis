"""把分析结果组装为网页与人工审计共同消费的报告结构。"""

from __future__ import annotations

from typing import Any

from .dimensions import analyze_keywords, analyze_profile, analyze_promotion, analyze_traffic
from .estimation import CORE_CARD_IDS, CORE_METRICS, to_number
from .product_assets import resolve_product_reference
from .sources import clean_identifier, clean_text


def format_number(value: float | None, digits: int = 2) -> str:
    """把数量或金额差距格式化为固定小数文本。"""

    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def ratio_label(self_value: float | None, competitor_value: float | None) -> str:
    """生成领先方倍率文本。"""

    if self_value is None or competitor_value is None or min(self_value, competitor_value) <= 0:
        return "无可比倍率"
    if self_value >= competitor_value:
        return f"本品 {self_value / competitor_value:.2f}x"
    return f"竞品 {competitor_value / self_value:.2f}x"


def gap_text(label: str, self_value: float | None, competitor_value: float | None) -> str:
    """生成统一领先或落后文案。"""

    if self_value is None or competitor_value is None:
        return "数据不足"
    direction = "领先" if self_value >= competitor_value else "落后"
    gap = f"{abs(self_value - competitor_value) * 100:.2f}pct" if label == "成交转化率" else format_number(abs(self_value - competitor_value))
    return f"本品{direction} {gap} | {ratio_label(self_value, competitor_value)}"


def build_core_views(core: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """生成核心对比和四张指标卡。

    功能说明：只基于核心估算最终值组装差距、倍率、状态与页面展示值，不执行任何估算。
    参数 core：估算模块输出的核心分析对象。
    返回值：完整核心对比数组和四张指标卡数组。
    """

    comparison = []
    cards = []
    for metric in CORE_METRICS:
        self_value = core["self_values"].get(metric.id)
        competitor_value = core["final_values"].get(metric.id)
        status = "advantage" if self_value is not None and competitor_value is not None and self_value >= competitor_value else "warning"
        comparison.append(
            {
                "metric_id": metric.id,
                "metric_label": metric.label,
                "self_value": self_value,
                "competitor_value": competitor_value,
                "gap": self_value - competitor_value if self_value is not None and competitor_value is not None else None,
                "gap_pct_point": (self_value - competitor_value) * 100 if metric.unit == "%" and self_value is not None and competitor_value is not None else None,
                "ratio": self_value / competitor_value if self_value and competitor_value else None,
                "judgement": "本品领先" if status == "advantage" else "本品落后",
            }
        )
        if metric.id not in CORE_CARD_IDS:
            continue
        card_self = self_value * 100 if metric.unit == "%" and self_value is not None else self_value
        card_competitor = competitor_value * 100 if metric.unit == "%" and competitor_value is not None else competitor_value
        cards.append(
            {
                "id": metric.id,
                "label": metric.label,
                "unit": metric.unit,
                "self_value": card_self,
                "competitor_value": card_competitor,
                "gap_abs_text": format_number(abs((self_value or 0) - (competitor_value or 0)) * (100 if metric.unit == "%" else 1)),
                "ratio_text": ratio_label(self_value, competitor_value),
                "gap_text": gap_text(metric.label, self_value, competitor_value),
                "status": status,
                "priority": "高" if status == "warning" else "低",
            }
        )
    return comparison, cards


def _select_balanced_highlights(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """优先各选一项优势和劣势，缺少时按原顺序补足两项。"""

    selected: list[dict[str, Any]] = []
    for status in ("advantage", "warning"):
        match = next((item for item in items if item["status"] == status), None)
        if match is not None:
            selected.append(match)
    for item in items:
        if len(selected) >= 2:
            break
        if item not in selected:
            selected.append(item)
    return selected


def _traffic_highlight_gap(item: dict[str, Any]) -> str:
    """生成人员可直接理解的渠道访客差距摘要。"""

    if item["self_visitors"] is None and item["competitor_visitors"] is not None:
        return f"竞品独有 | 竞品访客 {format_number(item['competitor_visitors'])}"
    if item["competitor_visitors"] is None and item["self_visitors"] is not None:
        return f"本品独有 | 本品访客 {format_number(item['self_visitors'])}"
    return gap_text("访客数", item["self_visitors"], item["competitor_visitors"])


def build_tabs(traffic: list[dict[str, Any]], keywords: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    """生成网页直接消费的三个分析 Tab。

    功能说明：从各分析域的最终结果生成重点数据、列定义、完整行和口径说明。
    参数 traffic：流量来源分析行。
    参数 keywords：关键词分析对象。
    参数 profile：客户画像分析对象。
    返回值：流量、关键词、客户画像三个稳定 Tab。
    """

    traffic_sorted = sorted(traffic, key=lambda item: abs(item["visitor_gap"]), reverse=True)
    traffic_highlights = _select_balanced_highlights(
        [
            {
                "label": item["path"],
                "self_value": item["self_visitors"],
                "competitor_value": item["competitor_visitors"],
                "unit": "",
                "gap_text": _traffic_highlight_gap(item),
                "status": "advantage" if item["visitor_gap"] >= 0 else "warning",
            }
            for item in traffic_sorted
        ]
    )
    traffic_rows = [
        {
            **item,
            "self_conversion_rate_pct": item["self_conversion_rate"] * 100 if item["self_conversion_rate"] is not None else None,
            "competitor_conversion_rate_pct": item["competitor_conversion_rate"] * 100 if item["competitor_conversion_rate"] is not None else None,
            "self_current_level_visitor_rate_pct": item["self_current_level_visitor_rate"] * 100 if item["self_current_level_visitor_rate"] is not None else None,
            "competitor_current_level_visitor_rate_pct": item["competitor_current_level_visitor_rate"] * 100 if item["competitor_current_level_visitor_rate"] is not None else None,
            "self_total_visitor_rate_pct": item["self_total_visitor_rate"] * 100 if item["self_total_visitor_rate"] is not None else None,
            "competitor_total_visitor_rate_pct": item["competitor_total_visitor_rate"] * 100 if item["competitor_total_visitor_rate"] is not None else None,
        }
        for item in traffic
    ]
    keyword_rows = [
        {
            **item,
            "self_visitor_share_pct": (
                item["self_visitor_share"] * 100 if item.get("self_visitor_share") is not None else None
            ),
            "competitor_visitor_share_pct": (
                item["competitor_visitor_share"] * 100
                if item.get("competitor_visitor_share") is not None
                else None
            ),
        }
        for item in keywords["rows"]
    ]
    keyword_highlights = _select_balanced_highlights(
        [
            {
                "label": item["keyword"],
                "self_value": item["self_visitors"],
                "competitor_value": item["competitor_visitors"],
                "unit": "",
                "gap_text": f"{item['opportunity']} | 访客差距 {format_number(item['visitor_gap'])} | 成交差距 {format_number(item['gmv_gap'])}",
                "status": "warning" if item["opportunity"] in {"补词机会", "访客落后", "成交落后"} else "advantage",
            }
            for item in keyword_rows
        ]
    )
    profile_rows = [item for dimension in profile["dimensions"] for item in dimension["items"]]
    comparable_profile = sorted(
        [item for item in profile_rows if item["gap_rate"] is not None],
        key=lambda item: abs(item["gap_rate"]),
        reverse=True,
    )
    profile_highlights = _select_balanced_highlights(
        [
            {
                "label": f"{item['dimension']}：{item['name']}",
                "self_value": item["self_rate"],
                "competitor_value": item["competitor_rate"],
                "unit": "%",
                "gap_text": f"{item['judgement']} | 差距 {abs(item['gap_rate']):.2f}pct",
                "status": "warning" if item["judgement"] == "本品落后" else "advantage",
            }
            for item in comparable_profile
        ]
    )
    return [
        {
            "id": "traffic",
            "label": "流量来源",
            "headline": "按渠道路径比较访客规模、成交金额和转化效率",
            "highlights": traffic_highlights,
            "columns": [
                {"key": "path", "label": "渠道路径"},
                {"key": "judgement", "label": "判断"},
                {"key": "visitor_gap", "label": "访客差距"},
                {"key": "gmv_gap", "label": "成交金额差距"},
                {"key": "conversion_gap_pct", "label": "转化差距", "unit": "pct"},
                {"key": "self_current_level_visitor_rate_pct", "label": "本品同层访客占比", "unit": "%"},
                {"key": "competitor_current_level_visitor_rate_pct", "label": "竞品同层访客占比", "unit": "%"},
                {"key": "self_total_visitor_rate_pct", "label": "本品总访客占比", "unit": "%"},
                {"key": "competitor_total_visitor_rate_pct", "label": "竞品总访客占比", "unit": "%"},
                {"key": "self_visitors", "label": "本品访客"},
                {"key": "competitor_visitors", "label": "竞品访客"},
                {"key": "self_gmv", "label": "本品成交金额"},
                {"key": "competitor_gmv", "label": "竞品成交金额"},
                {"key": "self_conversion_rate_pct", "label": "本品转化率", "unit": "%"},
                {"key": "competitor_conversion_rate_pct", "label": "竞品转化率", "unit": "%"},
            ],
            "rows": traffic_rows,
            "notes": ["同层访客占比按同一父渠道下的兄弟节点计算；总访客占比优先采用源表披露值。渠道值按原始区间估算，核心指标另受顶层渠道约束。"],
        },
        {
            "id": "keywords",
            "label": "关键词",
            "headline": "比较全部披露关键词的覆盖关系、访客和成交差距",
            "highlights": keyword_highlights,
            "columns": [
                {"key": "keyword", "label": "关键词"},
                {"key": "opportunity", "label": "机会判断"},
                {"key": "visitor_gap", "label": "访客差距"},
                {"key": "self_visitor_share_pct", "label": "本品访客占比", "unit": "%"},
                {"key": "competitor_visitor_share_pct", "label": "竞品访客占比", "unit": "%"},
                {"key": "gmv_gap", "label": "成交差距"},
                {"key": "coverage_relation", "label": "覆盖关系"},
                {"key": "self_visitors", "label": "本品访客"},
                {"key": "competitor_visitors", "label": "竞品访客"},
                {"key": "self_gmv", "label": "本品成交金额"},
                {"key": "competitor_gmv", "label": "竞品成交金额"},
            ],
            "rows": keyword_rows,
            "notes": keywords["notes"],
        },
        {
            "id": "customer_profile",
            "label": "客户画像",
            "headline": "按性别、年龄、地区、省份和城市维度比较成交客户结构",
            "highlights": profile_highlights,
            "dimension_field": "dimension",
            "dimension_label": "画像维度",
            "columns": [
                {"key": "name", "label": "画像项"},
                {"key": "judgement", "label": "判断"},
                {"key": "gap_rate", "label": "占比差距", "unit": "pct"},
                {"key": "self_rate", "label": "本品占比", "unit": "%"},
                {"key": "competitor_rate", "label": "竞品占比", "unit": "%"},
            ],
            "rows": profile_rows,
            "notes": profile["notes"],
        },
    ]


def build_analysis_result(
    normalized: dict[str, Any],
    core: dict[str, Any],
    product_images: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """组装最终分析结果。

    功能说明：消费标准化事实和核心估算结果，执行四个分析域并组装稳定的最终 JSON 契约。
    参数 normalized：单周期标准化事实数据。
    参数 core：核心估算与审计结果。
    参数 product_images：按商品 ID 索引的已校验主图素材。
    返回值：可供契约校验和网页消费的分析结果字典。
    """

    meta = normalized["meta"]
    self_row = normalized["self_real"]
    self_values = core["self_values"]
    final_values = core["final_values"]
    competitor_prefix = meta["competitor_prefix"]
    traffic = analyze_traffic(normalized["traffic_rows"], competitor_prefix)
    keywords = analyze_keywords(
        normalized["keyword_rows"],
        meta["self_spu"],
        meta["competitor_spu"],
        self_values.get("visitors"),
        self_values.get("gmv"),
        final_values.get("visitors"),
        final_values.get("gmv"),
    )
    profile = analyze_profile(
        normalized["customer_profile_rows"],
        competitor_prefix,
        to_number(self_row.get("成交人数")),
        core["competitor_buyers"],
    )
    promotion = analyze_promotion(normalized["promotion_rows"], competitor_prefix, final_values.get("gmv"))
    comparison, cards = build_core_views(core)
    tabs = build_tabs(traffic, keywords, profile)
    competitor_names = {
        clean_text(row.get("商品名称"))
        for row in normalized["keyword_rows"]
        if clean_identifier(row.get("SPUID")) == meta["competitor_spu"] and clean_text(row.get("商品名称"))
    }
    self_name = clean_text(self_row.get("商品名称")) or None
    competitor_name = sorted(competitor_names)[0] if competitor_names else None
    product_images = product_images or {}
    risks = list(core["risks"])
    source_status = {item["role"]: item["status"] for item in normalized["source_files"]}
    if source_status.get("keywords") != "ready":
        risks.append("缺少关键词数据，关键词 Tab 不完整")
    if source_status.get("customer_profile") != "ready":
        risks.append("缺少客户画像数据，客户画像 Tab 不完整")
    if not promotion["available"]:
        risks.append("缺少推广数据，投放判断不可用")
    risks.append("竞品数值为区间数据按当前 SOP 生成的准真实估算值")
    advantage_labels = [item["label"] for item in cards if item["status"] == "advantage"]
    warning_labels = [item["label"] for item in cards if item["status"] == "warning"]
    return {
        "schema_version": "1.0",
        "meta": {
            "title": meta.get("title") or "竞品准真实值看板",
            "period": meta["period"],
            "period_start": meta["period_start"],
            "period_end": meta["period_end"],
            "period_key": meta["period_key"],
            "granularity": meta["granularity"],
            "self_name": self_name,
            "self_spu": meta["self_spu"],
            "self_product": resolve_product_reference(meta["self_spu"], self_name, product_images),
            "competitor_name": competitor_name,
            "competitor_spu": meta["competitor_spu"],
            "competitor_product": resolve_product_reference(
                meta["competitor_spu"], competitor_name, product_images
            ),
            "confidence": core["report_confidence"],
            "summary": f"本品{'、'.join(advantage_labels)}领先。" if advantage_labels else "本品核心指标暂无明显优势。",
            "weakness_summary": f"本品{'、'.join(warning_labels)}落后，需要优先优化。" if warning_labels else "本品核心指标暂无明显短板。",
            "generated_at": meta["generated_at"],
        },
        "source_files": normalized["source_files"],
        "self_validation": core["validation"],
        "competitor_core_conversions": core["conversions"],
        "core_metrics": cards,
        "comparison": comparison,
        "traffic_sources": traffic,
        "keywords": keywords,
        "customer_profile": profile,
        "promotion": promotion,
        "tabs": tabs,
        "ai_recommendations": [],
        "risks": list(dict.fromkeys(risks)),
    }
