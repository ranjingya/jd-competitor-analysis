"""编排数仓事实计算与 AI 任务创建。"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from ..repositories.task_repository import TaskRepository


LOGGER = logging.getLogger(__name__)


def enqueue_ai_analysis(repository: TaskRepository, payload: dict[str, Any]) -> str:
    """为确定性分析结果创建 AI 任务。

    功能说明：对后端生成的结构化事实计算稳定哈希并写入任务仓库，供 Mac Codex 主动领取。
    参数 repository：AI 任务持久化仓库。
    参数 payload：已经完成 SKU→SPU、周期聚合和确定性指标计算的事实数据。
    返回值：新建 AI 分析任务 ID。
    """

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    analysis_id = repository.enqueue(source_hash=source_hash, payload=payload)
    LOGGER.info("确定性分析结果已进入 AI 队列：analysis_id=%s，source_hash=%s", analysis_id, source_hash)
    return analysis_id
