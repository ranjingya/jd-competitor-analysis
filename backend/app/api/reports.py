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


@router.get("/{report_id}")
def get_report_by_id(
    report_id: str,
    repository: ReportRepository = Depends(get_report_repository),
) -> dict[str, Any]:
    """按报告 ID 返回完整报告。

    功能说明：从统一 Backend 数据库读取一份可由 Web 直接消费的完整报告。
    参数 report_id：报告 ID。
    参数 repository：报告数据库仓库。
    返回值：完整报告 JSON。
    """

    try:
        return repository.get(report_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在") from error


@router.get("/{report_id}/skus")
def get_report_skus(
    report_id: str,
    repository: ReportRepository = Depends(get_report_repository),
) -> dict[str, Any]:
    """返回指定报告使用的本品 SKU 构成。

    功能说明：读取报告对应的日数据快照；周报和月报合并来源日报快照，返回固定五字段 SKU 列表。
    参数 report_id：报告 ID。
    参数 repository：报告数据库仓库。
    返回值：包含报告周期、本品 SPU 和 SKU 列表的对象。
    """

    try:
        return repository.get_skus(report_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在") from error


@router.get("/{granularity}/{start_date}/{end_date}")
def get_report(
    granularity: str,
    start_date: str,
    end_date: str,
    repository: ReportRepository = Depends(get_report_repository),
) -> dict[str, Any]:
    """返回指定粒度和周期的完整报告。

    功能说明：校验粒度和起止日期后读取单周期完整分析结果。
    参数 granularity：day、week 或 month 报告粒度。
    参数 start_date：周期开始日期。
    参数 end_date：周期结束日期。
    参数 repository：只读报告仓库。
    返回值：可直接由 Web 消费的完整报告 JSON。
    """

    try:
        return repository.read_report(granularity, start_date, end_date)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告不存在") from error
