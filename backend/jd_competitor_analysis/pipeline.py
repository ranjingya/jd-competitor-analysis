"""编排标准化数仓事实的确定性分析。"""

from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from typing import Any

from .contracts import validate_contract
from .estimation import PHistory, analyze_core
from .product_assets import load_product_images
from .report import build_analysis_result


LOGGER = logging.getLogger(__name__)


def analyze_normalized(
    normalized: dict[str, Any],
    history: PHistory | None = None,
    product_images: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """从标准化事实生成分析结果。

    功能说明：执行核心估算、分析域和报告组装，生成可拆分保存到 Backend 数据库的基础报告。
    参数 normalized：由数仓标准化日数据适配得到的单周期事实。
    参数 history：同商品、同粒度、此前周期的有效 P 样本。
    参数 product_images：按商品 ID 索引的主图素材；未传入时读取正式素材配置。
    返回值：最终分析结果与当前周期新增的有效 P 样本。
    """

    started_at = perf_counter()
    period_key = normalized.get("meta", {}).get("period_key")
    LOGGER.info("开始分析标准化事实：%s", period_key)
    core = analyze_core(normalized, history)
    resolved_product_images = product_images if product_images is not None else load_product_images()
    result = build_analysis_result(normalized, core, resolved_product_images)
    result["meta"]["generated_at"] = datetime.now().isoformat(timespec="seconds")
    validate_contract(result)
    LOGGER.info("标准化事实分析完成：%s，耗时=%.3fs", period_key, perf_counter() - started_at)
    return result, core["p_samples"]
