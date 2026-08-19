"""创建京东竞品分析 FastAPI 应用。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from .api.analysis_tasks import router as analysis_tasks_router
from .api.dependencies import get_database
from .api.reports import router as reports_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
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
app.include_router(reports_router)
app.include_router(analysis_tasks_router)


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    """返回容器健康状态。"""

    return {"status": "ok"}
