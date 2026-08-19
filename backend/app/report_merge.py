"""校验 AI 生成内容并合并到基础看板报告。"""

from __future__ import annotations

import copy
import logging
from typing import Any

from jd_competitor_analysis.contracts import validate_contract
from jd_competitor_analysis.recommendations import validate_recommendations


LOGGER = logging.getLogger(__name__)
FINDING_FIELDS = {"source_id", "target", "judgement", "evidence"}


def validate_findings(items: Any) -> list[dict[str, Any]]:
    """校验 AI 发现列表。

    功能说明：检查每条发现的来源、对象、判断和证据，避免空内容进入正式报告。
    参数 items：AI 回传的发现列表。
    返回值：通过校验的发现列表。
    """

    if not isinstance(items, list):
        raise ValueError("AI findings 必须是数组")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 项 AI finding 必须是对象")
        missing = sorted(FINDING_FIELDS - set(item))
        if missing:
            raise ValueError(f"第 {index} 项 AI finding 缺少字段：{missing}")
        if any(not isinstance(item[field], str) or not item[field].strip() for field in FINDING_FIELDS):
            raise ValueError(f"第 {index} 项 AI finding 存在空文本字段")
    return items


def validate_ai_result(result: dict[str, Any]) -> dict[str, Any]:
    """校验模型生成内容。

    功能说明：只接受总结、发现和建议三个 AI 字段；有建议时沿用正式建议约束，证据不足时允许空建议。
    参数 result：通过 API 基础 Schema 后的 AI 结果对象。
    返回值：经过复制和结构校验的 AI 结果。
    """

    if set(result) != {"summary", "findings", "recommendations"}:
        raise ValueError("AI 结果只能包含 summary、findings 和 recommendations")
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("AI summary 不能为空")
    findings = validate_findings(result.get("findings"))
    recommendations = result.get("recommendations")
    if recommendations:
        validate_recommendations(recommendations)
    elif recommendations != []:
        raise ValueError("AI recommendations 必须是数组")
    return {
        "summary": summary.strip(),
        "findings": copy.deepcopy(findings),
        "recommendations": copy.deepcopy(recommendations),
    }


def merge_ai_result(report: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """把 AI 生成部分合并到基础报告。

    功能说明：保留固定公式摘要用于审计，用 AI 总结更新看板摘要，并写入 AI 发现和建议后校验最终报告契约。
    参数 report：Backend 固定公式生成的基础看板报告。
    参数 result：DeepSeek 只生成的总结、发现和建议。
    返回值：可直接保存到 `reports.report_json` 的完整报告。
    """

    validated_result = validate_ai_result(result)
    merged = copy.deepcopy(report)
    meta = merged.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("基础报告缺少 meta 对象")
    meta.setdefault("deterministic_summary", meta.get("summary"))
    meta["summary"] = validated_result["summary"]
    merged["ai_findings"] = validated_result["findings"]
    merged["ai_recommendations"] = validated_result["recommendations"]
    validate_contract(merged)
    LOGGER.info(
        "AI 结果已合并到完整报告：findings=%s，recommendations=%s",
        len(validated_result["findings"]),
        len(validated_result["recommendations"]),
    )
    return merged
