"""提供 Mac Codex 使用的 AI 任务接口。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..auth import require_ai_worker
from ..config import Settings, get_settings
from ..repositories.task_repository import TaskConflictError, TaskRepository
from ..schemas import (
    ClaimedTask,
    ClaimRequest,
    CompleteTaskRequest,
    FailTaskRequest,
    TaskListResponse,
    TaskStatusResponse,
    TaskSummary,
)
from .dependencies import get_task_repository


router = APIRouter(
    prefix="/api/analysis-tasks",
    tags=["analysis-tasks"],
    dependencies=[Depends(require_ai_worker)],
)


@router.get("", response_model=TaskListResponse)
def list_tasks(
    task_status: (
        Literal["pending", "processing", "completed", "failed", "expired"] | None
    ) = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    repository: TaskRepository = Depends(get_task_repository),
) -> TaskListResponse:
    """查看最近的 AI 任务。

    功能说明：按生成时间倒序返回任务摘要，可按状态筛选，便于确认任务何时生成、当前状态和对应商品对。
    参数 task_status：可选任务状态筛选条件。
    参数 limit：最多返回的任务数量，范围为 1–100。
    参数 repository：AI 任务持久化仓库。
    返回值：任务数量及摘要列表，不包含任务正文、租约令牌和 AI 结果。
    """

    tasks = [TaskSummary.model_validate(item) for item in repository.list_recent(task_status, limit)]
    return TaskListResponse(count=len(tasks), tasks=tasks)


@router.post("/claim", response_model=ClaimedTask, responses={204: {"description": "没有待分析任务"}})
def claim_task(
    request: ClaimRequest,
    settings: Settings = Depends(get_settings),
    repository: TaskRepository = Depends(get_task_repository),
) -> ClaimedTask | Response:
    """领取一条 AI 分析任务。

    功能说明：按创建时间原子领取待分析任务，没有任务时返回 204。
    参数 request：包含当前 Mac Worker 标识的请求。
    参数 settings：提供任务租约时长的后端配置。
    参数 repository：AI 任务持久化仓库。
    返回值：已领取任务及其数据哈希和租约，或 204 空响应。
    """

    task = repository.claim(request.worker_id, settings.task_lease_seconds)
    if task is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return ClaimedTask.model_validate(task)


@router.post("/{analysis_id}/complete", response_model=TaskStatusResponse)
def complete_task(
    analysis_id: str,
    request: CompleteTaskRequest,
    repository: TaskRepository = Depends(get_task_repository),
) -> TaskStatusResponse:
    """校验租约并保存 Codex 分析结果。

    功能说明：校验任务 ID、数据哈希和有效租约，幂等保存 AI 生成内容并由 Backend 合并完整报告。
    参数 analysis_id：需要完成的任务 ID。
    参数 request：数据哈希、租约令牌和 AI 分析结果。
    参数 repository：AI 任务持久化仓库。
    返回值：包含任务 ID 和 completed 状态的响应。
    """

    try:
        repository.complete(
            analysis_id=analysis_id,
            source_hash=request.source_hash,
            lease_token=request.lease_token,
            result=request.result.model_dump(),
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from error
    except TaskConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return TaskStatusResponse(analysis_id=analysis_id, status="completed")


@router.post("/{analysis_id}/fail", response_model=TaskStatusResponse)
def fail_task(
    analysis_id: str,
    request: FailTaskRequest,
    repository: TaskRepository = Depends(get_task_repository),
) -> TaskStatusResponse:
    """记录 Codex 分析失败原因。

    功能说明：校验任务租约后保存失败原因，避免不完整结果进入完成状态。
    参数 analysis_id：需要标记失败的任务 ID。
    参数 request：租约令牌和可排查的失败原因。
    参数 repository：AI 任务持久化仓库。
    返回值：包含任务 ID 和 failed 状态的响应。
    """

    try:
        repository.fail(analysis_id, request.lease_token, request.error)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from error
    except TaskConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return TaskStatusResponse(analysis_id=analysis_id, status="failed")
