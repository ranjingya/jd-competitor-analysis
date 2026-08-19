"""编排数仓事实计算与 AI 任务创建。"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from ..repositories.dataset_repository import DatasetRepository
from ..repositories.report_repository import ReportRepository
from ..repositories.task_repository import TaskRepository


LOGGER = logging.getLogger(__name__)


def persist_daily_dataset(repository: DatasetRepository, payload: dict[str, Any]) -> str:
    """保存完整标准化日数据。

    功能说明：将 Backend 组装完成的日数据写入统一数据库，并复用内容相同的数据版本。
    参数 repository：标准化数据集仓库。
    参数 payload：包含日期、商品对、来源数据和质量状态的完整日数据。
    返回值：新建或已存在的数据集 ID。
    """

    dataset_id = repository.store(payload)
    LOGGER.info("标准化日数据已持久化：dataset_id=%s", dataset_id)
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

    report_id = repository.upsert(dataset_id, report, status="pending_ai")
    LOGGER.info("基础报告已持久化：report_id=%s，dataset_id=%s", report_id, dataset_id)
    return report_id


def enqueue_ai_analysis(
    repository: TaskRepository,
    dataset_id: str,
    payload: dict[str, Any],
) -> str:
    """为确定性分析结果创建 AI 任务。

    功能说明：对后端生成的结构化事实计算稳定哈希并写入任务仓库，供 Mac Codex 主动领取。
    参数 repository：AI 任务持久化仓库。
    参数 dataset_id：AI 输入所属的标准化数据集 ID。
    参数 payload：已经完成 SKU→SPU、周期聚合和确定性指标计算的事实数据。
    返回值：新建 AI 分析任务 ID。
    """

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    analysis_id = repository.enqueue(
        dataset_id=dataset_id,
        source_hash=source_hash,
        payload=payload,
    )
    LOGGER.info("确定性分析结果已进入 AI 队列：analysis_id=%s，source_hash=%s", analysis_id, source_hash)
    return analysis_id
