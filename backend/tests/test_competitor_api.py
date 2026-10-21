"""验证竞品版本化接口的业务一致性和错误契约，不访问正式数据。"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import FastAPI

from app.api.competitor import router
from app.api.dependencies import get_report_repository
from app.api.reports import router as legacy_router
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.report_repository import ReportRepository
from report_fixture import build_report_fixture


class CompetitorApiTest(unittest.TestCase):
    """使用临时数据库和内存 ASGI 调用核对所有只读端点。"""

    def setUp(self):
        """建立独立测试库及报告，不运行正式应用启动流程。"""
        self.temp = tempfile.TemporaryDirectory()
        datasets = DatasetRepository(Path(self.temp.name) / "test.db")
        datasets.initialize()
        dataset_id = datasets.store({
            "report_date": "2026-08-17", "pair": {"self_spu": "10001", "competitor_spu": "20001"},
            "self_product": {"sku_components": [{"spu_id": "10001", "sku_id": "30001",
                "barcode_69": None, "product_name": "测试商品", "specification": "测试规格"}]},
            "quality": {"status": "partial"},
        })
        self.repository = ReportRepository(Path(self.temp.name) / "test.db")
        fixture = build_report_fixture()
        fixture["historical_extension"] = {"zero": 0, "missing": None}
        self.report_id = self.repository.upsert(dataset_id, fixture, status="ready")
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.include_router(legacy_router)
        self.app.dependency_overrides[get_report_repository] = lambda: self.repository

    def tearDown(self):
        """释放测试文件。"""
        self.temp.cleanup()

    def get(self, path, **query):
        """功能说明：执行内存 GET；path 为路径，query 为查询参数；返回 HTTP 状态和 JSON，无网络请求。"""
        async def invoke():
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
                "query_string": urlencode(query).encode(), "headers": [], "root_path": "",
                "server": ("test", 80), "client": ("test", 1)}, receive, send)
            status = next(m["status"] for m in messages if m["type"] == "http.response.start")
            body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
            return status, json.loads(body)

        return asyncio.run(invoke())

    def test_all_report_endpoints_preserve_repository_results(self):
        """新接口封套内与仓库逐字段一致，扩展字段、零及缺失值均保留。"""
        scope = {"self_spu": "10001", "competitor_spu": "20001", "granularity": "day"}
        cases = [
            ("/product-pairs", {}, self.repository.list_product_pairs()),
            ("/reports/periods", {**scope, "context": "2026-08"}, self.repository.list_periods(**scope, context="2026-08")),
            ("/reports/trends", {**scope, "start_date": "2026-08-17", "end_date": "2026-08-17"},
                self.repository.read_trends(**scope, start_date="2026-08-17", end_date="2026-08-17")),
            (f"/reports/{self.report_id}", {}, self.repository.get(self.report_id)),
            (f"/reports/{self.report_id}/skus", {}, self.repository.get_skus(self.report_id)),
        ]
        with self.repository.database.connection() as connection:
            before = list(connection.iterdump())
        for path, query, expected in cases:
            with self.subTest(path=path):
                status, body = self.get("/api/v1/competitor" + path, **query)
                self.assertEqual(status, 200, body)
                self.assertEqual(body, {"data": expected})
        with self.repository.database.connection() as connection:
            self.assertEqual(list(connection.iterdump()), before)

    def test_legacy_report_remains_unchanged(self):
        """旧页面继续读取原响应，没有被新增封套影响。"""
        status, body = self.get(f"/api/reports/{self.report_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.repository.get(self.report_id))

    def test_errors_are_structured_and_do_not_expose_internal_details(self):
        """缺报告、缺参数、非法周期和内部故障均有独立错误响应。"""
        for path, query, expected in [
            ("/reports/missing", {}, 404), ("/reports/periods", {}, 422),
            ("/reports/periods", {"self_spu": "10001", "competitor_spu": "20001", "granularity": "day", "context": "invalid"}, 400),
            ("/reports/periods", {"self_spu": "10001", "competitor_spu": "20001", "granularity": "year", "context": "2026"}, 400),
            ("/reports/trends", {"self_spu": "10001", "competitor_spu": "20001", "granularity": "day", "start_date": "invalid", "end_date": "2026-08-17"}, 400),
            ("/reports/trends", {"self_spu": "10001", "competitor_spu": "20001", "granularity": "day", "start_date": "2026-08-18", "end_date": "2026-08-17"}, 400),
        ]:
            status, body = self.get("/api/v1/competitor" + path, **query)
            self.assertEqual(status, expected)
            self.assertIn("error", body)
            self.assertNotIn("data", body)
        with patch.object(self.repository, "get", side_effect=RuntimeError("private database path")):
            status, body = self.get("/api/v1/competitor/reports/test")
            self.assertEqual(status, 500)
            self.assertNotIn("private", str(body))

    def test_internal_value_errors_are_read_failures(self):
        """存储解析与内部数值异常返回脱敏的读取故障，不向客户端暴露内部信息。"""
        for error in [ValueError("private database value"), json.JSONDecodeError("private report", "", 0)]:
            with self.subTest(error=type(error).__name__), patch.object(self.repository, "get", side_effect=error):
                status, body = self.get("/api/v1/competitor/reports/test")
                self.assertEqual(status, 500)
                self.assertEqual(body["error"]["code"], "INTERNAL_ERROR")
                self.assertNotIn("private", str(body))

    def test_corrupt_stored_report_returns_internal_error(self):
        """持久化报告的 JSON 损坏时返回服务端错误，不修改已有数据或分析任务。"""
        with self.repository.database.connection() as connection:
            connection.execute("UPDATE reports SET audit_json = ? WHERE report_id = ?", ("{broken", self.report_id))
        status, body = self.get(f"/api/v1/competitor/reports/{self.report_id}")
        self.assertEqual(status, 500)
        self.assertEqual(body["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("broken", str(body))
        with self.repository.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT audit_json FROM reports WHERE report_id = ?", (self.report_id,)).fetchone()[0], "{broken")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM analysis_tasks").fetchone()[0], 0)

    def test_status_and_openapi(self):
        """状态查询只读取既有快照，六个接口均声明数据及错误模型。"""
        snapshot = {"schema_version": "1.0", "status": "idle", "stage": "idle",
                    "process_alive": False, "progress_age_seconds": None, "stale": False}
        with patch("app.api.competitor.get_settings") as settings, patch(
            "app.api.competitor.read_daily_analysis_status", return_value=snapshot
        ) as read:
            status, body = self.get("/api/v1/competitor/analysis-status")
            self.assertEqual((status, body), (200, {"data": snapshot}))
            read.assert_called_once_with(settings.return_value.analysis_status_path)
        paths = {k: v for k, v in self.app.openapi()["paths"].items() if k.startswith("/api/v1/competitor/")}
        self.assertEqual(len(paths), 6)
        for endpoint in paths.values():
            for code in ("200", "400", "404", "422", "500"):
                self.assertIn("$ref", endpoint["get"]["responses"][code]["content"]["application/json"]["schema"])
