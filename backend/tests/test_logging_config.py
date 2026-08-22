"""测试 Backend 日志格式与健康检查过滤。"""

from __future__ import annotations

import logging
import unittest

from app.logging_config import HealthCheckAccessFilter


def _access_record(path: str) -> logging.LogRecord:
    """生成一条与 Uvicorn 参数结构一致的访问日志。"""

    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "GET", path, "1.1", 200),
        exc_info=None,
    )


class HealthCheckAccessFilterTest(unittest.TestCase):
    """验证仅隐藏健康检查访问日志。"""

    def test_health_check_access_is_filtered(self) -> None:
        """健康检查路径及其查询参数均不应写入访问日志。"""

        selected_filter = HealthCheckAccessFilter()

        self.assertFalse(selected_filter.filter(_access_record("/healthz")))
        self.assertFalse(selected_filter.filter(_access_record("/healthz?probe=1")))

    def test_business_api_access_is_preserved(self) -> None:
        """普通 API 与相似路径应继续输出访问日志。"""

        selected_filter = HealthCheckAccessFilter()

        self.assertTrue(selected_filter.filter(_access_record("/api/reports")))
        self.assertTrue(selected_filter.filter(_access_record("/healthz/detail")))


if __name__ == "__main__":
    unittest.main()
