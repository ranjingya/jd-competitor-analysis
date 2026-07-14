"""把 Skill 生成的 AI 建议安全写入分析结果。"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any


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


def read_json(path: Path) -> Any:
    """读取 UTF-8 JSON。

    功能说明：读取并解析指定 JSON 文件，在日志中记录输入位置。
    参数 path：需要读取的 JSON 文件路径。
    返回值：解析后的 Python 对象。
    """

    LOGGER.info("读取 JSON：%s", path)
    return json.loads(path.read_text(encoding="utf-8"))


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

    analysis = read_json(analysis_path)
    payload = read_json(recommendations_path)
    expected_period = analysis.get("meta", {}).get("period_key")
    if payload.get("period_key") != expected_period:
        raise ValueError(
            f"建议周期与分析结果不一致：{payload.get('period_key')} != {expected_period}"
        )
    analysis["ai_recommendations"] = validate_recommendations(payload.get("ai_recommendations"))
    temp_path = analysis_path.with_suffix(f"{analysis_path.suffix}.tmp")
    temp_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(analysis_path)
    LOGGER.info("AI 建议已写入：%s", analysis_path)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    功能说明：读取分析结果路径和 AI 建议输入路径。
    返回值：包含 `analysis` 与 `recommendations` 路径的参数对象。
    """

    parser = argparse.ArgumentParser(description="把 Skill 生成的 AI 建议写入 analysis_result.json")
    parser.add_argument("--analysis", type=Path, required=True, help="analysis_result.json 路径")
    parser.add_argument("--recommendations", type=Path, required=True, help="AI 建议输入 JSON 路径")
    return parser.parse_args()


def main() -> None:
    """执行 AI 建议写入流程。

    功能说明：初始化日志、解析参数、校验输入并更新正式分析结果。
    返回值：无。
    """

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    LOGGER.info("开始写入 AI 建议")
    apply_recommendations(args.analysis, args.recommendations)
    LOGGER.info("AI 建议写入完成")


if __name__ == "__main__":
    main()
