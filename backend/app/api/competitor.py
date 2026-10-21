"""提供 React 看板使用的版本化只读接口，不触发同步或分析。"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from ..config import get_settings
from ..job_status import read_daily_analysis_status
from ..repositories.report_repository import ReportQueryError, ReportRepository
from .contracts import AnalysisStatus, Envelope, ErrorResponse, ProductPairs, Periods, Report, ReportSkus, Trends
from .dependencies import get_report_repository

LOGGER = logging.getLogger(__name__)


class ReadRoute(APIRoute):
    """将版本化接口的异常转为稳定错误结构，不影响旧接口。"""

    def get_route_handler(self):
        """功能说明：包装只读接口；参数 self 为路由；返回含日志和异常处理的异步处理函数。"""
        handler = super().get_route_handler()

        async def read(request: Request):
            """功能说明：执行查询；参数 request 为请求；返回数据或结构化错误响应。"""
            LOGGER.info("竞品查询开始：接口=%s", self.path)
            try:
                response = await handler(request)
                LOGGER.info("竞品查询完成：接口=%s 状态=%s", self.path, response.status_code)
                return response
            except FileNotFoundError:
                code, message, status, details = "NOT_FOUND", "报告不存在", 404, []
            except RequestValidationError as error:
                code, message, status = "INVALID_REQUEST", "请求参数不正确", 422
                details = [{"field": ".".join(map(str, e["loc"])), "reason": e["type"]} for e in error.errors()]
            except ReportQueryError as error:
                code, message, status, details = "INVALID_REQUEST", str(error), 400, []
            except Exception:
                LOGGER.exception("竞品查询异常：接口=%s", self.path)
                code, message, status, details = "INTERNAL_ERROR", "报告读取失败，请稍后重试", 500, []
            LOGGER.warning("竞品查询失败：接口=%s 错误=%s 状态=%s", self.path, code, status)
            return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})

        return read


router = APIRouter(
    prefix="/api/v1/competitor", tags=["competitor"], route_class=ReadRoute,
    responses={code: {"model": ErrorResponse} for code in (400, 404, 422, 500)},
)


@router.get("/product-pairs", response_model=Envelope[ProductPairs])
def product_pairs(repository: ReportRepository = Depends(get_report_repository)):
    """功能说明：读取商品对；参数 repository 为报告仓库；返回导航索引封套。"""
    return {"data": repository.list_product_pairs()}


@router.get("/reports/periods", response_model=Envelope[Periods])
def periods(self_spu: str, competitor_spu: str, granularity: str, context: str,
            repository: ReportRepository = Depends(get_report_repository)):
    """功能说明：查询可用周期；self_spu 为本品，competitor_spu 为竞品，granularity 为粒度，context 为年月，repository 为仓库；返回周期封套。"""
    return {"data": repository.list_periods(self_spu, competitor_spu, granularity, context)}


@router.get("/reports/trends", response_model=Envelope[Trends])
def trends(self_spu: str, competitor_spu: str, granularity: str, start_date: str, end_date: str,
           repository: ReportRepository = Depends(get_report_repository)):
    """功能说明：查询轻量趋势；self_spu 为本品，competitor_spu 为竞品，granularity 为粒度，start_date/end_date 为日期范围，repository 为仓库；返回趋势封套。"""
    return {"data": repository.read_trends(self_spu, competitor_spu, granularity, start_date, end_date)}


@router.get("/reports/{report_id}", response_model=Envelope[Report])
def report(report_id: str, repository: ReportRepository = Depends(get_report_repository)):
    """功能说明：读取完整报告；report_id 为报告标识，repository 为仓库；返回历史报告封套。"""
    return {"data": repository.get(report_id)}


@router.get("/reports/{report_id}/skus", response_model=Envelope[ReportSkus])
def report_skus(report_id: str, repository: ReportRepository = Depends(get_report_repository)):
    """功能说明：读取 SKU 快照；report_id 为报告标识，repository 为仓库；返回 SKU 封套。"""
    return {"data": repository.get_skus(report_id)}


@router.get("/analysis-status", response_model=Envelope[AnalysisStatus])
def analysis_status():
    """功能说明：读取现有任务状态文件；无参数；返回状态封套，不启动任务。"""
    return {"data": read_daily_analysis_status(get_settings().analysis_status_path)}
