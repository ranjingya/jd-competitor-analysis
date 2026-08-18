"""提供看板报告查询接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ..repositories.report_repository import ReportRepository
from .dependencies import get_report_repository


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def list_reports(repository: ReportRepository = Depends(get_report_repository)) -> dict[str, Any]:
    """返回日、周、月报告索引。

    功能说明：读取后端报告目录中的轻量索引，并将报告地址转换为 API 路径。
    参数 repository：只读报告仓库。
    返回值：包含 day、week 和 month 数组的报告索引。
    """

    try:
        return repository.read_index()
    except (ValueError, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"报告索引不可用：{error}",
        ) from error


@router.get("/{granularity}/{period_directory}")
def get_report(
    granularity: str,
    period_directory: str,
    repository: ReportRepository = Depends(get_report_repository),
) -> dict[str, Any]:
    """返回指定粒度和周期的完整报告。

    功能说明：校验粒度与周期目录后读取单周期完整分析结果。
    参数 granularity：day、week 或 month 报告粒度。
    参数 period_directory：日期或日期区间目录。
    参数 repository：只读报告仓库。
    返回值：可直接由 Web 消费的完整报告 JSON。
    """

    try:
        return repository.read_report(granularity, period_directory)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在") from error
