"""维护 JSON 空结构、读写和最终契约校验。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .report import build_tabs


LOGGER = logging.getLogger(__name__)


def empty_contract() -> dict[str, Any]:
    """生成符合最终分析契约的空结构模板。"""

    empty_keywords = {
        "summary": {"common_count": 0, "self_only_count": 0, "competitor_only_count": 0},
        "coverage": {
            "self_visitor_rate": None,
            "competitor_visitor_rate": None,
            "self_gmv_rate": None,
            "competitor_gmv_rate": None,
        },
        "rows": [],
        "notes": [],
    }
    empty_profile = {"dimensions": [], "notes": []}
    return {
        "schema_version": "1.0",
        "meta": {
            "title": None,
            "period": None,
            "period_start": None,
            "period_end": None,
            "period_key": None,
            "granularity": None,
            "self_name": None,
            "self_spu": None,
            "competitor_name": None,
            "competitor_spu": None,
            "confidence": None,
            "summary": None,
            "weakness_summary": None,
        },
        "source_files": [],
        "self_validation": [],
        "competitor_core_conversions": [],
        "core_metrics": [],
        "comparison": [],
        "traffic_sources": [],
        "keywords": empty_keywords,
        "customer_profile": empty_profile,
        "promotion": {
            "available": False,
            "self": {},
            "competitor": {},
            "attributed_gmv_rate": None,
            "judgement": None,
            "notes": [],
        },
        "tabs": build_tabs([], empty_keywords, empty_profile),
        "ai_recommendations": [],
        "risks": [],
    }


def validate_contract(data: dict[str, Any], allow_empty: bool = False) -> None:
    """校验最终分析 JSON。

    功能说明：检查顶层模块、周期字段、核心指标、三个 Tab 和 AI 建议结构，失败时阻止写出。
    参数 data：待校验的分析结果字典。
    参数 allow_empty：是否允许指标和明细为空，用于空结构模板。
    返回值：无；契约不完整时抛出 ValueError。
    """

    required_top = {
        "schema_version",
        "meta",
        "source_files",
        "self_validation",
        "competitor_core_conversions",
        "core_metrics",
        "comparison",
        "traffic_sources",
        "keywords",
        "customer_profile",
        "promotion",
        "tabs",
        "ai_recommendations",
        "risks",
    }
    missing = sorted(required_top - set(data))
    if missing:
        raise ValueError(f"analysis_result 缺少顶层字段：{missing}")
    required_meta = {"period", "period_start", "period_end", "period_key", "granularity"}
    missing_meta = sorted(required_meta - set(data["meta"]))
    if missing_meta:
        raise ValueError(f"analysis_result.meta 缺少周期字段：{missing_meta}")
    if not isinstance(data["risks"], list) or any(not isinstance(item, str) for item in data["risks"]):
        raise ValueError("risks 必须是字符串数组")
    if not isinstance(data["ai_recommendations"], list):
        raise ValueError("ai_recommendations 必须是数组")
    for item in data["ai_recommendations"]:
        for field in ("source_id", "source_label", "target", "status", "evidence", "actions", "validation"):
            if field not in item:
                raise ValueError(f"AI 建议缺少字段：{field}")
        if not isinstance(item["actions"], list) or not item["actions"]:
            raise ValueError("AI 建议 actions 必须是非空数组")
    tab_map = {tab.get("id"): tab for tab in data["tabs"]}
    if set(tab_map) != {"traffic", "keywords", "customer_profile"}:
        raise ValueError(f"tabs 必须包含 traffic、keywords、customer_profile，当前={sorted(tab_map)}")
    for tab_id, tab in tab_map.items():
        for field in ("label", "headline", "highlights", "columns", "rows", "notes"):
            if field not in tab:
                raise ValueError(f"Tab {tab_id} 缺少字段：{field}")
    if not allow_empty:
        if len(data["core_metrics"]) != 4:
            raise ValueError("正式结果必须包含四张核心指标卡")
        for item in data["core_metrics"]:
            for field in ("id", "label", "unit", "self_value", "competitor_value", "gap_text", "status"):
                if field not in item:
                    raise ValueError(f"核心指标卡缺少字段：{field}")
        for item in data["competitor_core_conversions"]:
            for field in ("metric_id", "candidate_source", "selected_candidate", "final_value", "confidence", "checks"):
                if field not in item:
                    raise ValueError(f"核心转换审计缺少字段：{field}")
    LOGGER.info("JSON 契约校验通过：allow_empty=%s", allow_empty)


def read_json(path: Path) -> Any:
    """读取 UTF-8 JSON。"""

    LOGGER.info("读取 JSON：%s", path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    """以 UTF-8 和缩进格式原子写入 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    LOGGER.info("已写入 JSON：%s", path)
