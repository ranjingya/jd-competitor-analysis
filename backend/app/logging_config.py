"""统一 Backend 业务日志与 Uvicorn 日志。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any


LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)s %(name)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
BEIJING_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")


class BeijingFormatter(logging.Formatter):
    """使用 Asia/Shanghai 时区格式化日志时间。"""

    def formatTime(
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        """将日志时间转换为北京时间。

        功能说明：忽略容器系统时区，直接以 Asia/Shanghai 输出日志时间。
        参数 record：包含 Unix 时间戳的日志记录。
        参数 datefmt：可选时间格式字符串。
        返回值：格式化后的北京时间文本。
        """

        selected_time = datetime.fromtimestamp(record.created, BEIJING_TIMEZONE)
        return selected_time.strftime(datefmt) if datefmt else selected_time.isoformat()


class HealthCheckAccessFilter(logging.Filter):
    """过滤 Uvicorn 对 `/healthz` 的访问日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """判断一条访问日志是否需要输出。

        功能说明：读取 Uvicorn 访问日志参数中的请求路径，仅隐藏健康检查端点；其他日志全部保留。
        参数 record：待处理的标准日志记录。
        返回值：`/healthz` 请求返回 False，其他记录返回 True。
        """

        arguments: Any = record.args
        if isinstance(arguments, tuple) and len(arguments) >= 3:
            request_path = str(arguments[2]).partition("?")[0]
            return request_path != "/healthz"
        return True


def configure_backend_logging(level: int = logging.INFO) -> None:
    """配置 Backend 与 Uvicorn 日志。

    功能说明：为业务、Uvicorn 错误和访问日志统一添加日期与毫秒时间，并过滤健康检查访问记录。
    参数 level：根日志级别，默认 INFO。
    返回值：无；直接更新当前进程中的标准日志处理器。
    """

    formatter = BeijingFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    logging.basicConfig(level=level)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers:
            handler.setFormatter(formatter)

    access_logger = logging.getLogger("uvicorn.access")
    for handler in access_logger.handlers:
        if not any(isinstance(item, HealthCheckAccessFilter) for item in handler.filters):
            handler.addFilter(HealthCheckAccessFilter())
