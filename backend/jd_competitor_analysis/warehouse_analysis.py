"""将数仓标准化日数据接入现有确定性分析。"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any

from .pipeline import analyze_normalized


LOGGER = logging.getLogger(__name__)
DEFAULT_TITLE = "竞品准真实值看板"
COMPETITOR_PREFIX = "竞品1"
CORE_METRIC_FIELDS = (
    ("page_views", "浏览量"),
    ("visitors", "访客数"),
    ("add_to_cart_users", "加购人数"),
    ("orders", "成交单量"),
    ("units_sold", "成交商品件数"),
    ("gmv", "成交金额"),
    ("conversion_rate", "成交转化率"),
    ("average_order_value", "成交客单价"),
    ("search_clicks", "搜索点击次数"),
)
PROFILE_DIMENSION_LABELS = {
    "gender": "性别",
    "age": "年龄",
    "region": "地区",
    "province": "省份",
    "city": "城市",
    "unknown": "其他",
}
AI_EXCLUDED_REPORT_FIELDS = {"tabs", "ai_findings", "ai_recommendations"}
AI_SOURCE_FILE_FIELDS = ("role", "label", "required_level", "status", "warnings")


def _metric_raw(metric: Any) -> Any:
    """从固定指标对象提取供现有公式解析的源值。"""

    return metric.get("raw") if isinstance(metric, dict) else None


def _analysis_source_status(source: dict[str, Any]) -> str:
    """把数仓字段质量状态转换为旧版分析使用的来源可用状态。

    功能说明：旧版分析只区分整块来源是否可读取；数仓的 partial 表示部分字段未披露，
    但记录仍可用于分析，因此应继续按 ready 处理。只有整块来源不可用时才返回 missing。
    参数 source：包含 records 和 quality 的数仓标准化来源对象。
    返回值：旧版确定性分析使用的 ready 或 missing 状态。
    """

    quality_status = source.get("quality", {}).get("status")
    return "ready" if quality_status in {"ready", "partial"} else "missing"


def _first_product_name(dataset: dict[str, Any]) -> str | None:
    """从本品 SKU 构成中提取首个非空商品名。"""

    components = dataset.get("self_product", {}).get("sku_components", [])
    return next(
        (
            str(item["product_name"])
            for item in components
            if isinstance(item, dict) and item.get("product_name")
        ),
        None,
    )


def _adapt_core(dataset: dict[str, Any]) -> dict[str, Any]:
    """把固定核心指标对象转换为现有分析公式输入。"""

    records = dataset["sources"]["core_metrics"]["records"]
    if not records:
        raise ValueError("标准化日数据缺少核心指标记录")
    record = records[0]
    result: dict[str, Any] = {}
    for metric_id, label in CORE_METRIC_FIELDS:
        result[f"本品{label}"] = _metric_raw(record.get("self", {}).get(metric_id))
        result[f"{COMPETITOR_PREFIX}{label}"] = _metric_raw(
            record.get("competitor", {}).get(metric_id)
        )
    return result


def _adapt_traffic(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """把流量来源固定记录转换为现有渠道分析输入。"""

    rows = []
    for record in dataset["sources"]["traffic_sources"]["records"]:
        row = {
            "一级渠道": record.get("channel_level_1"),
            "二级渠道": record.get("channel_level_2"),
            "三级渠道": record.get("channel_level_3"),
        }
        for side_key, prefix in (("self", "本品"), ("competitor", COMPETITOR_PREFIX)):
            side = record.get(side_key, {})
            row[f"{prefix}访客数"] = _metric_raw(side.get("visitors"))
            row[f"{prefix}访客数占比"] = _metric_raw(side.get("visitor_share"))
            row[f"{prefix}成交金额"] = _metric_raw(side.get("gmv"))
            row[f"{prefix}成交转化率"] = _metric_raw(side.get("conversion_rate"))
            row[f"{prefix}成交客户数"] = _metric_raw(side.get("buyers"))
        rows.append(row)
    return rows


def _adapt_keywords(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """把关键词固定记录转换为现有关键词分析输入。"""

    return [
        {
            "SPUID": record.get("spu_id"),
            "商品名称": record.get("product_name"),
            "关键词": record.get("keyword"),
            "访客数": _metric_raw(record.get("visitors")),
            "成交金额": _metric_raw(record.get("gmv")),
        }
        for record in dataset["sources"]["traffic_keywords"]["records"]
    ]


def _adapt_profiles(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """把画像固定记录恢复为带维度标题的现有分析输入。"""

    rows: list[dict[str, Any]] = []
    current_dimension: str | None = None
    for record in dataset["sources"]["customer_profiles"]["records"]:
        dimension = str(record.get("dimension") or "unknown")
        if dimension != current_dimension:
            rows.append({"画像类型": PROFILE_DIMENSION_LABELS.get(dimension, "其他")})
            current_dimension = dimension
        rows.append(
            {
                "画像类型": record.get("segment"),
                "本品成交客户数占比": _metric_raw(record.get("self_share")),
                f"{COMPETITOR_PREFIX}成交客户数占比": _metric_raw(
                    record.get("competitor_share")
                ),
            }
        )
    return rows


def _adapt_promotion(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    """把推广固定记录转换为现有推广分析输入。"""

    rows = []
    for record in dataset["sources"]["promotion"]["records"]:
        row: dict[str, Any] = {}
        for side_key, prefix in (("self", "本店商品"), ("competitor", COMPETITOR_PREFIX)):
            side = record.get(side_key, {})
            row[f"全站-{prefix}全站交易额"] = _metric_raw(side.get("full_site", {}).get("gmv"))
            row[f"全站-{prefix}核心位置点击数"] = _metric_raw(
                side.get("full_site", {}).get("core_position_clicks")
            )
            row[f"非全站-{prefix}广告点击数"] = _metric_raw(
                side.get("non_full_site", {}).get("ad_clicks")
            )
            row[f"非全站-{prefix}广告总订单金额"] = _metric_raw(
                side.get("non_full_site", {}).get("ad_order_gmv")
            )
        rows.append(row)
    return rows


def adapt_daily_dataset(dataset: dict[str, Any], title: str | None = None) -> dict[str, Any]:
    """将数仓标准化日数据转换为确定性分析输入。

    功能说明：保留本品 SPU 真实汇总值和竞品区间原文，将五个来源映射到现有 P 值、约束和分析域函数需要的稳定字段。
    参数 dataset：符合数仓日数据标准化契约的完整数据集。
    参数 title：可选看板标题。
    返回值：可直接传给 `analyze_normalized` 的日维度分析输入。
    """

    if dataset.get("quality", {}).get("status") == "invalid":
        raise ValueError("质量状态为 invalid 的数据集不能生成正式报告")
    report_date = str(dataset["report_date"])
    pair = dataset["pair"]
    self_metrics = dataset["self_product"]["spu_daily_metrics"]
    self_real = {
        label: self_metrics.get(metric_id)
        for metric_id, label in CORE_METRIC_FIELDS
    }
    self_real["成交人数"] = self_metrics.get("buyers")
    self_real["商品名称"] = _first_product_name(dataset)
    source_roles = {
        "core_metrics": "core",
        "traffic_sources": "traffic",
        "traffic_keywords": "keywords",
        "customer_profiles": "customer_profile",
        "promotion": "promotion",
    }
    normalized = {
        "meta": {
            "title": title or DEFAULT_TITLE,
            "period": report_date,
            "period_start": report_date,
            "period_end": report_date,
            "period_key": f"day:{report_date}",
            "granularity": "day",
            "self_spu": pair["self_spu"],
            "competitor_spu": pair["competitor_spu"],
            "competitor_prefix": COMPETITOR_PREFIX,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "self_real": self_real,
        "core_raw": _adapt_core(dataset),
        "traffic_rows": _adapt_traffic(dataset),
        "keyword_rows": _adapt_keywords(dataset),
        "customer_profile_rows": _adapt_profiles(dataset),
        "promotion_rows": _adapt_promotion(dataset),
        "source_files": [
            {
                "role": role,
                "status": _analysis_source_status(dataset["sources"][source_id]),
                "source": dataset["sources"][source_id]["source"]["table"],
            }
            for source_id, role in source_roles.items()
        ],
    }
    LOGGER.info(
        "数仓日数据已适配确定性分析：date=%s，compare_number=%s",
        report_date,
        pair["compare_number"],
    )
    return normalized


def analyze_daily_dataset(
    dataset: dict[str, Any],
    title: str | None = None,
    product_images: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """对一份数仓标准化日数据执行固定公式分析。

    功能说明：适配数仓事实后执行现有 P 值、区间约束、差距和分析域计算，不调用 AI。
    参数 dataset：完整标准化日数据集。
    参数 title：可选看板标题。
    参数 product_images：可选商品主图索引；测试时可传空对象。
    返回值：可写入报告表的基础看板对象。
    """

    normalized = adapt_daily_dataset(dataset, title)
    report, _ = analyze_normalized(normalized, product_images=product_images)
    return report


def _full_report_facts(report: dict[str, Any]) -> dict[str, Any]:
    """构建不丢失业务行的完整准真实值分析事实。

    功能说明：复制后端确定性报告的全部分析字段，仅移除页面渲染结构、已有 AI 内容、易变时间和图片地址，并将来源信息收敛为分析状态。
    参数 report：固定公式生成、尚未合并当前 AI 结果的完整基础报告。
    返回值：可直接保存为 AI 输入快照的完整分析事实。
    """

    facts = copy.deepcopy(report)
    for field in AI_EXCLUDED_REPORT_FIELDS:
        facts.pop(field, None)
    meta = facts.get("meta", {})
    meta.pop("generated_at", None)
    for product_field in ("self_product", "competitor_product"):
        product = meta.get(product_field)
        if isinstance(product, dict):
            product.pop("image_url", None)
    facts["source_files"] = [
        {
            field: copy.deepcopy(item.get(field))
            for field in AI_SOURCE_FILE_FIELDS
            if field in item
        }
        for item in facts.get("source_files", [])
    ]
    return facts


def build_ai_task_payload(
    dataset_id: str,
    dataset: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    """生成稳定且不包含易变时间的 AI 任务事实。

    功能说明：组合数据集标识、质量、SKU 完整性和完整准真实值分析事实，不筛选任何关键词、画像或流量业务行。
    参数 dataset_id：标准化数据集 ID。
    参数 dataset：完整标准化日数据集。
    参数 report：固定公式生成的基础报告。
    返回值：供后端 DeepSeek 分析器读取的只读结构化事实。
    """

    self_product = dataset["self_product"]
    self_quality = self_product["quality"]
    return {
        "schema_version": "1.2",
        "dataset_id": dataset_id,
        "report_date": dataset["report_date"],
        "pair": dataset["pair"],
        "data_quality": dataset["quality"],
        "self_product": {
            "sku_count": len(self_product["sku_components"]),
            "quality": {
                "status": self_quality.get("status"),
                "mapped_sku_count": self_quality.get("mapped_sku_count"),
                "warehouse_sku_count": self_quality.get("warehouse_sku_count"),
                "ready_sku_count": self_quality.get("ready_sku_count"),
                "missing_sku_count": len(self_quality.get("missing_sku_ids", [])),
                "partial_sku_count": len(self_quality.get("partial_sku_ids", [])),
                "issues": copy.deepcopy(self_quality.get("issues", [])),
            },
        },
        "analysis_facts": _full_report_facts(report),
    }
