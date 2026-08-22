"""校验结构化 AI 劣势建议。"""

from __future__ import annotations

import logging
from typing import Any


LOGGER = logging.getLogger(__name__)
ALLOWED_SOURCES = {"traffic", "keywords", "customer_profile", "promotion"}
REQUIRED_STATUS = "warning"
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
    """校验 AI 劣势建议结构。

    功能说明：检查劣势建议数量、来源、状态、证据、动作和验收条件，阻止不完整内容写入正式报告。
    参数 items：DeepSeek 返回的建议数组。
    返回值：通过校验的建议数组。
    """

    if not isinstance(items, list) or not 2 <= len(items) <= 5:
        raise ValueError("AI 劣势建议必须是包含 2–5 项的数组")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 项 AI 劣势建议必须是对象")
        missing = sorted(REQUIRED_FIELDS - set(item))
        if missing:
            raise ValueError(f"第 {index} 项 AI 劣势建议缺少字段：{missing}")
        if item["source_id"] not in ALLOWED_SOURCES:
            raise ValueError(f"第 {index} 项 AI 劣势建议来源无效：{item['source_id']}")
        if item["status"] != REQUIRED_STATUS:
            raise ValueError(f"第 {index} 项 AI 劣势建议状态必须为 warning：{item['status']}")
        if not isinstance(item["actions"], list) or not 1 <= len(item["actions"]) <= 3:
            raise ValueError(f"第 {index} 项 AI 劣势建议 actions 必须包含 1–3 条动作")
        text_fields = ("source_label", "target", "evidence", "validation")
        if any(not isinstance(item[field], str) or not item[field].strip() for field in text_fields):
            raise ValueError(f"第 {index} 项 AI 劣势建议存在空文本字段")
        if any(not isinstance(action, str) or not action.strip() for action in item["actions"]):
            raise ValueError(f"第 {index} 项 AI 劣势建议 actions 存在空动作")
    represented_sources = {item["source_id"] for item in items}
    if len(represented_sources) < 2:
        raise ValueError("AI 劣势建议必须覆盖至少两个不同来源")
    LOGGER.info("AI 劣势建议结构校验通过：%s 项", len(items))
    return items
