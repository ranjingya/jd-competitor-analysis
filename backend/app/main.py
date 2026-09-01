"""创建京东竞品分析 FastAPI 应用。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from .api.dependencies import get_database
from .api.reports import product_pairs_router, router as reports_router
from .config import get_settings
from .job_status import read_daily_analysis_status
from .logging_config import configure_backend_logging


configure_backend_logging()
LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """管理后端应用生命周期。

    功能说明：应用启动时初始化统一 Backend 数据库，关闭时记录停止日志。
    参数 _：FastAPI 应用实例，当前无需直接读取。
    返回值：异步生命周期上下文。
    """

    LOGGER.info("京东竞品分析后端开始启动")
    get_database().initialize()
    yield
    LOGGER.info("京东竞品分析后端已停止")


app = FastAPI(title="京东竞品分析 API", lifespan=lifespan)
app.include_router(product_pairs_router)
app.include_router(reports_router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    """返回容器健康状态。"""

    return {"status": "ok"}


@app.get("/api/analysis-status", tags=["system"])
def analysis_status() -> dict[str, object]:
    """返回日报批处理的最近运行状态。

    功能说明：读取共享数据目录中的原子状态快照，供部署人员判断任务阶段和最近进度。
    返回值：包含运行状态、阶段、商品对、进度时间和计数的对象。
    """

    return read_daily_analysis_status(get_settings().analysis_status_path)
