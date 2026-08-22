"""编排数仓事实、基础报告和内部 AI 执行记录。"""

from __future__ import annotations

import hashlib
import json
import logging
from time import perf_counter
from typing import Any

from ..repositories.dataset_repository import DatasetRepository
from ..repositories.report_repository import ReportRepository
from ..repositories.task_repository import TaskRepository, TaskStartResult


LOGGER = logging.getLogger(__name__)
DEFAULT_ANALYSIS_VERSION = "1.0"


def persist_daily_dataset(repository: DatasetRepository, payload: dict[str, Any]) -> str:
    """保存完整标准化日数据。

    功能说明：将 Backend 组装完成的日数据写入统一数据库，并复用内容相同的数据版本。
    参数 repository：标准化数据集仓库。
    参数 payload：包含日期、商品对、来源数据和质量状态的完整日数据。
    返回值：新建或已存在的数据集 ID。
    """

    started_at = perf_counter()
    dataset_id = repository.store(payload)
    LOGGER.info(
        "标准化日数据已持久化：dataset_id=%s，耗时=%.3fs",
        dataset_id,
        perf_counter() - started_at,
    )
    return dataset_id


def persist_base_report(
    repository: ReportRepository,
    dataset_id: str,
    report: dict[str, Any],
) -> str:
    """保存等待 AI 补充的基础报告。

    功能说明：将确定性计算生成的看板对象写入统一数据库，并标记为等待 AI 分析。
    参数 repository：报告仓库。
    参数 dataset_id：报告所属标准化数据集 ID。
    参数 report：可供 Web 消费的基础报告对象。
    返回值：新建或已存在的报告 ID。
    """

    started_at = perf_counter()
    report_id = repository.upsert(dataset_id, report, status="pending_ai")
    LOGGER.info(
        "基础报告已持久化：report_id=%s，dataset_id=%s，耗时=%.3fs",
        report_id,
        dataset_id,
        perf_counter() - started_at,
    )
    return report_id


def start_ai_analysis(
    repository: TaskRepository,
    report_id: str,
    payload: dict[str, Any],
    model: str,
    analysis_version: str = DEFAULT_ANALYSIS_VERSION,
    prompt_hash: str = "",
) -> TaskStartResult:
    """为确定性分析结果启动内部 AI 执行。

    功能说明：对后端生成的结构化事实计算稳定哈希并写入任务仓库，判断是否需要调用当前模型。
    参数 repository：AI 执行记录持久化仓库。
    参数 report_id：AI 结果最终更新的唯一报告 ID。
    参数 payload：已经完成 SKU→SPU、周期聚合和确定性指标计算的事实数据。
    参数 model：本次使用的 DeepSeek 模型标识。
    参数 analysis_version：AI 分析规则版本。
    参数 prompt_hash：当前提示词内容哈希。
    返回值：执行记录 ID 与本次是否需要调用模型。
    """

    started_at = perf_counter()
    source = {
        "payload": payload,
        "model": model,
        "analysis_version": analysis_version,
        "prompt_hash": prompt_hash,
    }
    serialized = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    result = repository.start(
        report_id=report_id,
        source_hash=source_hash,
        payload=payload,
        model=model,
        analysis_version=analysis_version,
        prompt_hash=prompt_hash,
    )
    LOGGER.info(
        "内部 AI 执行已准备：analysis_id=%s，model=%s，execute=%s，source_hash=%s，耗时=%.3fs",
        result.analysis_id,
        model,
        result.should_execute,
        source_hash,
        perf_counter() - started_at,
    )
    return result
