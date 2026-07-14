"""分析流量、关键词、成交客户画像和推广数据。"""

from __future__ import annotations

from typing import Any

from .estimation import parse_range
from .sources import clean_identifier, clean_text


DIMENSION_NAMES = {"性别", "年龄", "地区", "省份", "城市"}


def enrich_traffic_visitor_rates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """补充渠道访客的同层占比和总占比。

    功能说明：按同一父渠道分组计算兄弟节点访客占比，并整理源表披露的全渠道访客占比。
    参数 rows：已完成层级路径、两侧访客值和源表访客占比解析的渠道行。
    返回值：补充两侧同层访客占比和总访客占比后的渠道行。
    """

    sibling_totals: dict[tuple[str, ...], dict[str, float]] = {}
    root_totals = {"self_visitors": 0.0, "competitor_visitors": 0.0}
    for row in rows:
        levels = tuple(
            value for value in (row.get("level_1"), row.get("level_2"), row.get("level_3")) if value and value != "-"
        )
        totals = sibling_totals.setdefault(levels[:-1], {"self_visitors": 0.0, "competitor_visitors": 0.0})
        for visitor_key in ("self_visitors", "competitor_visitors"):
            value = row.get(visitor_key)
            if isinstance(value, (int, float)):
                totals[visitor_key] += value
                if len(levels) == 1:
                    root_totals[visitor_key] += value

    for row in rows:
        levels = tuple(
            value for value in (row.get("level_1"), row.get("level_2"), row.get("level_3")) if value and value != "-"
        )
        totals = sibling_totals.get(levels[:-1], {})
        for side in ("self", "competitor"):
            visitor_key = f"{side}_visitors"
            source_rate_key = f"{side}_visitor_rate"
            value = row.get(visitor_key)
            sibling_total = totals.get(visitor_key)
            total_value = root_totals.get(visitor_key)
            row[f"{side}_current_level_visitor_rate"] = (
                value / sibling_total if isinstance(value, (int, float)) and sibling_total else None
            )
            source_total_rate = row.get(source_rate_key)
            row[f"{side}_total_visitor_rate"] = (
                source_total_rate
                if isinstance(source_total_rate, (int, float))
                else value / total_value if isinstance(value, (int, float)) and total_value else None
            )
    return rows


def analyze_traffic(rows: list[dict[str, Any]], competitor_prefix: str) -> list[dict[str, Any]]:
    """解析完整流量来源并生成渠道差距。

    功能说明：读取三级渠道区间，生成层级路径、两侧估算值、访客占比与差距判断。
    参数 rows：流量来源标准化原始行。
    参数 competitor_prefix：目标竞品字段前缀。
    返回值：完整渠道分析行。
    """

    result = []
    for row in rows:
        levels = [clean_text(row.get(key)) for key in ("一级渠道", "二级渠道", "三级渠道")]
        path_parts = [value for value in levels if value and value != "-"]
        if not path_parts:
            continue
        self_visitors = parse_range(row.get("本品访客数")).mid
        competitor_visitors = parse_range(row.get(f"{competitor_prefix}访客数")).mid
        self_gmv = parse_range(row.get("本品成交金额")).mid
        competitor_gmv = parse_range(row.get(f"{competitor_prefix}成交金额")).mid
        self_rate = parse_range(row.get("本品成交转化率")).mid
        competitor_rate = parse_range(row.get(f"{competitor_prefix}成交转化率")).mid
        visitor_gap = (self_visitors or 0) - (competitor_visitors or 0)
        gmv_gap = (self_gmv or 0) - (competitor_gmv or 0)
        rate_gap = ((self_rate or 0) - (competitor_rate or 0)) * 100
        judgement = "本品领先" if visitor_gap >= 0 and gmv_gap >= 0 else "本品落后" if visitor_gap < 0 and gmv_gap < 0 else "结构分化"
        result.append(
            {
                "level_1": levels[0] or None,
                "level_2": levels[1] or None,
                "level_3": levels[2] or None,
                "path": " > ".join(path_parts),
                "self_visitors": self_visitors,
                "competitor_visitors": competitor_visitors,
                "self_visitor_rate": parse_range(row.get("本品访客数占比")).mid,
                "competitor_visitor_rate": parse_range(row.get(f"{competitor_prefix}访客数占比")).mid,
                "self_gmv": self_gmv,
                "competitor_gmv": competitor_gmv,
                "self_conversion_rate": self_rate,
                "competitor_conversion_rate": competitor_rate,
                "self_customers": parse_range(row.get("本品成交客户数")).mid,
                "competitor_customers": parse_range(row.get(f"{competitor_prefix}成交客户数")).mid,
                "visitor_gap": visitor_gap,
                "gmv_gap": gmv_gap,
                "conversion_gap_pct": rate_gap,
                "judgement": judgement,
                "estimation_basis": "区间中位数；核心指标另受顶层渠道约束",
            }
        )
    return enrich_traffic_visitor_rates(result)


def analyze_keywords(
    rows: list[dict[str, Any]],
    self_spu: str,
    competitor_spu: str,
    self_visitors: float | None,
    self_gmv: float | None,
    competitor_visitors: float | None,
    competitor_gmv: float | None,
) -> dict[str, Any]:
    """生成关键词外连接、覆盖率和机会判断。

    功能说明：按商品归集关键词，以完整外连接比较两侧 Top 关键词并计算覆盖率。
    参数 rows：关键词标准化原始行。
    参数 self_spu：本品 SPU。
    参数 competitor_spu：竞品 SPU。
    参数 self_visitors：本品真实访客数。
    参数 self_gmv：本品真实成交金额。
    参数 competitor_visitors：竞品估算访客数。
    参数 competitor_gmv：竞品估算成交金额。
    返回值：关键词摘要、覆盖率、完整行和口径说明。
    """

    grouped: dict[str, dict[str, dict[str, Any]]] = {"self": {}, "competitor": {}}
    for row in rows:
        spu = clean_identifier(row.get("SPUID"))
        side = "self" if spu == self_spu else "competitor" if spu == competitor_spu else None
        keyword = clean_text(row.get("关键词"))
        if side and keyword:
            grouped[side][keyword.casefold()] = row
    keys = sorted(set(grouped["self"]) | set(grouped["competitor"]))
    result_rows = []
    for key in keys:
        self_row = grouped["self"].get(key)
        competitor_row = grouped["competitor"].get(key)
        display_keyword = clean_text((self_row or competitor_row or {}).get("关键词"))
        self_keyword_visitors = parse_range(self_row.get("访客数") if self_row else None).mid
        competitor_keyword_visitors = parse_range(competitor_row.get("访客数") if competitor_row else None).mid
        self_keyword_gmv = parse_range(self_row.get("成交金额") if self_row else None).mid
        competitor_keyword_gmv = parse_range(competitor_row.get("成交金额") if competitor_row else None).mid
        relation = "共同词" if self_row and competitor_row else "本品独有" if self_row else "竞品独有"
        visitor_gap = (self_keyword_visitors or 0) - (competitor_keyword_visitors or 0)
        gmv_gap = (self_keyword_gmv or 0) - (competitor_keyword_gmv or 0)
        if relation == "竞品独有":
            opportunity = "补词机会"
        elif relation == "本品独有":
            opportunity = "保持优势"
        elif visitor_gap < 0:
            opportunity = "访客落后"
        elif gmv_gap < 0:
            opportunity = "成交落后"
        else:
            opportunity = "本品领先"
        result_rows.append(
            {
                "keyword": display_keyword,
                "coverage_relation": relation,
                "self_visitors": self_keyword_visitors,
                "competitor_visitors": competitor_keyword_visitors,
                "visitor_gap": visitor_gap,
                "self_gmv": self_keyword_gmv,
                "competitor_gmv": competitor_keyword_gmv,
                "gmv_gap": gmv_gap,
                "opportunity": opportunity,
            }
        )
    result_rows.sort(key=lambda item: max(abs(item["gmv_gap"]), abs(item["visitor_gap"])), reverse=True)
    self_visitor_sum = sum(item["self_visitors"] or 0 for item in result_rows)
    competitor_visitor_sum = sum(item["competitor_visitors"] or 0 for item in result_rows)
    self_gmv_sum = sum(item["self_gmv"] or 0 for item in result_rows)
    competitor_gmv_sum = sum(item["competitor_gmv"] or 0 for item in result_rows)
    return {
        "summary": {
            "common_count": sum(item["coverage_relation"] == "共同词" for item in result_rows),
            "self_only_count": sum(item["coverage_relation"] == "本品独有" for item in result_rows),
            "competitor_only_count": sum(item["coverage_relation"] == "竞品独有" for item in result_rows),
        },
        "coverage": {
            "self_visitor_rate": self_visitor_sum / self_visitors if self_visitors else None,
            "competitor_visitor_rate": competitor_visitor_sum / competitor_visitors if competitor_visitors else None,
            "self_gmv_rate": self_gmv_sum / self_gmv if self_gmv else None,
            "competitor_gmv_rate": competitor_gmv_sum / competitor_gmv if competitor_gmv else None,
        },
        "rows": result_rows,
        "notes": ["关键词列表为 Top 口径，合计不代表商品全量。"],
    }


def analyze_profile(
    rows: list[dict[str, Any]],
    competitor_prefix: str,
    self_buyers: float | None,
    competitor_buyers: float | None,
) -> dict[str, Any]:
    """解析成交客户画像。

    功能说明：识别画像维度标题，比较各画像项占比并换算两侧估算人数。
    参数 rows：客户画像标准化原始行。
    参数 competitor_prefix：竞品字段前缀。
    参数 self_buyers：本品真实成交人数。
    参数 competitor_buyers：竞品估算成交人数。
    返回值：按维度组织的画像分析结果。
    """

    dimensions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        name = clean_text(row.get("画像类型"))
        self_interval = parse_range(row.get("本品成交客户数占比"))
        competitor_interval = parse_range(row.get(f"{competitor_prefix}成交客户数占比"))
        if name in DIMENSION_NAMES and self_interval.missing and competitor_interval.missing:
            current = {"dimension": name, "items": []}
            dimensions.append(current)
            continue
        if not name or current is None:
            continue
        self_rate = self_interval.mid * 100 if self_interval.mid is not None else None
        competitor_rate = competitor_interval.mid * 100 if competitor_interval.mid is not None else None
        gap_rate = self_rate - competitor_rate if self_rate is not None and competitor_rate is not None else None
        judgement = "无完整口径" if gap_rate is None else "本品领先" if gap_rate >= 1 else "本品落后" if gap_rate <= -1 else "基本持平"
        current["items"].append(
            {
                "dimension": current["dimension"],
                "name": name,
                "self_rate": self_rate,
                "competitor_rate": competitor_rate,
                "gap_rate": gap_rate,
                "self_estimated_customers": self_buyers * self_rate / 100 if self_buyers is not None and self_rate is not None else None,
                "competitor_estimated_customers": competitor_buyers * competitor_rate / 100 if competitor_buyers is not None and competitor_rate is not None else None,
                "judgement": judgement,
            }
        )
    return {"dimensions": dimensions, "notes": ["各画像维度分别比较；缺失值不等同于 0。"]}


def analyze_promotion(rows: list[dict[str, Any]], competitor_prefix: str, competitor_gmv: float | None) -> dict[str, Any]:
    """解析推广点击、归因成交和贡献比例。

    功能说明：读取推广区间中位值，计算竞品广告归因成交占比并保留口径提示。
    参数 rows：推广数据标准化原始行。
    参数 competitor_prefix：竞品字段前缀。
    参数 competitor_gmv：竞品核心成交金额估算值。
    返回值：稳定的推广分析对象。
    """

    if not rows:
        return {"available": False, "self": {}, "competitor": {}, "attributed_gmv_rate": None, "judgement": "数据不足", "notes": []}
    row = rows[0]
    self_clicks = parse_range(row.get("非全站-本店商品广告点击数")).mid
    self_gmv = parse_range(row.get("非全站-本店商品广告总订单金额")).mid
    competitor_clicks = parse_range(row.get(f"非全站-{competitor_prefix}广告点击数")).mid
    competitor_ad_gmv = parse_range(row.get(f"非全站-{competitor_prefix}广告总订单金额")).mid
    attributed_rate = competitor_ad_gmv / competitor_gmv if competitor_ad_gmv is not None and competitor_gmv else None
    return {
        "available": True,
        "self": {"ad_clicks": self_clicks, "ad_order_gmv": self_gmv},
        "competitor": {"ad_clicks": competitor_clicks, "ad_order_gmv": competitor_ad_gmv},
        "attributed_gmv_rate": attributed_rate,
        "judgement": "竞品投放贡献较高" if attributed_rate is not None and attributed_rate >= 0.3 else "竞品投放贡献有限",
        "notes": ["推广成交为广告归因口径，不与核心 SPU 成交金额强制对齐。"],
    }
