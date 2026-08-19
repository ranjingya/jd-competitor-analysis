"""定义后端 API 数据结构。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClaimRequest(BaseModel):
    """领取 AI 分析任务时提交的 Worker 信息。"""

    worker_id: str = Field(min_length=1, max_length=100)


class ClaimedTask(BaseModel):
    """后端返回给 Codex 的已领取任务。"""

    analysis_id: str
    dataset_id: str
    report_date: str
    compare_number: str
    self_spu: str
    competitor_spu: str
    created_at: str
    attempt_count: int
    source_hash: str
    lease_token: str
    lease_expires_at: str
    payload: dict[str, Any]


class TaskSummary(BaseModel):
    """供人工查看的 AI 任务摘要。"""

    analysis_id: str
    dataset_id: str
    report_date: str
    compare_number: str
    self_spu: str
    competitor_spu: str
    status: str
    worker_id: str | None
    attempt_count: int
    created_at: str
    updated_at: str
    lease_expires_at: str | None
    completed_at: str | None
    error_message: str | None


class TaskListResponse(BaseModel):
    """AI 任务列表响应。"""

    count: int
    tasks: list[TaskSummary]


class AIAnalysisResult(BaseModel):
    """Codex 生成的结构化分析结果。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)


class CompleteTaskRequest(BaseModel):
    """完成任务时提交的租约、数据版本和 AI 结果。"""

    source_hash: str = Field(min_length=1)
    lease_token: str = Field(min_length=1)
    result: AIAnalysisResult


class FailTaskRequest(BaseModel):
    """任务失败时提交的租约和错误原因。"""

    lease_token: str = Field(min_length=1)
    error: str = Field(min_length=1, max_length=4000)


class TaskStatusResponse(BaseModel):
    """任务状态变更结果。"""

    analysis_id: str
    status: str
