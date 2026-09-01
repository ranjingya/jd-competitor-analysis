"""提供看板报告查询接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ..repositories.report_repository import ReportRepository
from .dependencies import get_report_repository


router = APIRouter(prefix="/api/reports", tags=["reports"])
product_pairs_router = APIRouter(prefix="/api/product-pairs", tags=["product-pairs"])


@product_pairs_router.get("")
def list_product_pairs(
    repository: ReportRepository = Depends(get_report_repository),
) -> dict[str, Any]:
    """返回商品对和最新报告导航信息。

    功能说明：页面首次打开时仅返回商品对、各粒度最新报告和数量。
    参数 repository：报告数据库仓库。
    返回值：商品对列表及最近更新时间。
    """

    return repository.list_product_pairs()


@router.get("/periods")
def list_report_periods(
    self_spu: str,
    competitor_spu: str,
    granularity: str,
    context: str,
    repository: ReportRepository = Depends(get_report_repository),
) -> dict[str, Any]:
    """返回当前日历上下文的可用报告。

    功能说明：日期选择器展开或切换年月时，按商品对和上下文读取轻量报告条目。
    参数 self_spu：本品 SPU。
    参数 competitor_spu：竞品 SPU。
    参数 granularity：day、week 或 month。
    参数 context：日报/周报月份 YYYY-MM，或月报年份 YYYY。
    参数 repository：报告数据库仓库。
    返回值：当前上下文报告、可导航上下文和报告元数据。
    """

    try:
        return repository.list_periods(
            self_spu,
            competitor_spu,
            granularity,
            context,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/trends")
def get_report_trends(
    self_spu: str,
    competitor_spu: str,
    granularity: str,
    start_date: str,
    end_date: str,
    repository: ReportRepository = Depends(get_report_repository),
) -> dict[str, Any]:
    """返回核心指标轻量趋势。

    功能说明：只读取成交金额、访客数、转化率和客单价，供趋势图异步展示。
    参数 self_spu：本品 SPU。
    参数 competitor_spu：竞品 SPU。
    参数 granularity：day、week 或 month。
    参数 start_date：报告开始日期下界。
    参数 end_date：报告开始日期上界。
    参数 repository：报告数据库仓库。
    返回值：指定范围的轻量核心指标报告数组。
    """

    try:
        return repository.read_trends(
            self_spu,
            competitor_spu,
            granularity,
            start_date,
            end_date,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


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
