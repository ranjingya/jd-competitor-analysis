"""校验并写入 Skill 生成的结构化 AI 建议。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .contracts import read_json, validate_contract, write_json


LOGGER = logging.getLogger(__name__)
ALLOWED_SOURCES = {"traffic", "keywords", "customer_profile"}
ALLOWED_STATUSES = {"warning", "advantage", "neutral"}
REQUIRED_FIELDS = {
    "source_id",
    "source_label",
    "target",
    "status",
    "evidence",
    "actions",
    "validation",
}


def validate_recommendations(items: Any) -> list[dict[str, Any]]:
    """校验 AI 建议结构。

    功能说明：检查建议数量、来源、状态、证据、动作和验收条件，阻止不完整内容写入正式报告。
    参数 items：Skill 生成的建议数组。
    返回值：通过校验的建议数组。
    """

    if not isinstance(items, list) or not 1 <= len(items) <= 5:
        raise ValueError("AI 建议必须是包含 1–5 项的数组")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 项 AI 建议必须是对象")
        missing = sorted(REQUIRED_FIELDS - set(item))
        if missing:
            raise ValueError(f"第 {index} 项 AI 建议缺少字段：{missing}")
        if item["source_id"] not in ALLOWED_SOURCES:
            raise ValueError(f"第 {index} 项 AI 建议来源无效：{item['source_id']}")
        if item["status"] not in ALLOWED_STATUSES:
            raise ValueError(f"第 {index} 项 AI 建议状态无效：{item['status']}")
        if not isinstance(item["actions"], list) or not 1 <= len(item["actions"]) <= 3:
            raise ValueError(f"第 {index} 项 AI 建议 actions 必须包含 1–3 条动作")
        text_fields = ("source_label", "target", "evidence", "validation")
        if any(not isinstance(item[field], str) or not item[field].strip() for field in text_fields):
            raise ValueError(f"第 {index} 项 AI 建议存在空文本字段")
        if any(not isinstance(action, str) or not action.strip() for action in item["actions"]):
            raise ValueError(f"第 {index} 项 AI 建议 actions 存在空动作")
    LOGGER.info("AI 建议结构校验通过：%s 项", len(items))
    return items


def apply_recommendations(analysis_path: Path, recommendations_path: Path) -> None:
    """把建议写入分析结果。

    功能说明：读取正式分析结果与 Skill 产出的建议，校验周期一致性后原子更新 `ai_recommendations`。
    参数 analysis_path：需要更新的 `analysis_result.json` 路径。
    参数 recommendations_path：包含 `period_key` 和 `ai_recommendations` 的输入 JSON 路径。
    返回值：无；成功后原子覆盖分析结果文件。
    """

    LOGGER.info("开始写入 AI 建议：%s", analysis_path)
    analysis = read_json(analysis_path)
    payload = read_json(recommendations_path)
    expected_period = analysis.get("meta", {}).get("period_key")
    if payload.get("period_key") != expected_period:
        raise ValueError(f"建议周期与分析结果不一致：{payload.get('period_key')} != {expected_period}")
    analysis["ai_recommendations"] = validate_recommendations(payload.get("ai_recommendations"))
    validate_contract(analysis)
    write_json(analysis_path, analysis)
    LOGGER.info("AI 建议写入完成：%s", analysis_path)
