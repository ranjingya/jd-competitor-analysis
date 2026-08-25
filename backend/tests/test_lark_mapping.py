"""测试飞书多维表 SPU/SKU 只读映射。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from jd_competitor_analysis.lark_mapping import (
    LarkBaseConfig,
    LarkBaseMappingClient,
    load_lark_base_config,
)


class FakeRequester:
    """按分页返回固定飞书响应，并记录请求。"""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        """保存测试分页数据。"""

        self.pages = pages
        self.calls: list[tuple[str, str, dict[str, str], dict[str, Any] | None, int]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """返回凭证或指定页响应。"""

        self.calls.append((method, url, headers, payload, timeout_seconds))
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return {"code": 0, "msg": "ok", "tenant_access_token": "test-token", "expire": 7200}
        query = parse_qs(urlparse(url).query)
        page_index = 1 if query.get("page_token") == ["next-page"] else 0
        return self.pages[page_index]


def _record(spu_id: str, sku_id: str, barcode: str, name: str, specification: str) -> dict[str, Any]:
    """构造一条测试多维表记录。"""

    return {
        "record_id": f"rec-{sku_id}",
        "fields": {
            "主商品条码": spu_id,
            "子商品条码": sku_id,
            "69码": barcode,
            "商品名称": name,
            "规格": specification,
        },
    }


class LarkBaseMappingClientTest(unittest.TestCase):
    """验证映射筛选、分页、字段保留和只读请求。"""

    def setUp(self) -> None:
        """创建不包含真实凭据的客户端配置。"""

        self.config = LarkBaseConfig(
            app_id="test-app",
            app_secret="test-secret",
            base_token="baseToken123",
            table_id="tblMapping123",
            pair_table_id="tblPair123",
            page_size=100,
            api_base_url="https://example.invalid/open-apis",
        )

    def test_mapping_keeps_five_fields_and_reads_all_pages(self) -> None:
        """查询结果应完整保留五个业务字段并处理分页。"""

        requester = FakeRequester(
            [
                {
                    "code": 0,
                    "data": {
                        "items": [_record("10001", "10003", "69003", "商品 A", "蓝色 L")],
                        "has_more": True,
                        "page_token": "next-page",
                    },
                },
                {
                    "code": 0,
                    "data": {
                        "items": [_record("10001", "10002", "69002", "商品 A", "蓝色 M")],
                        "has_more": False,
                    },
                },
            ]
        )
        client = LarkBaseMappingClient(self.config, requester=requester)

        mappings = client.list_spu_sku_mappings("10001")

        self.assertEqual([mapping.sku_id for mapping in mappings], ["10002", "10003"])
        self.assertEqual(mappings[0].barcode_69, "69002")
        self.assertEqual(mappings[0].product_name, "商品 A")
        self.assertEqual(mappings[0].specification, "蓝色 M")
        self.assertEqual([call[0] for call in requester.calls], ["POST", "GET", "GET"])
        for method, url, _, _, _ in requester.calls[1:]:
            self.assertEqual(method, "GET")
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query["filter"], ['CurrentValue.[主商品条码]="10001"'])

    def test_tenant_token_is_reused(self) -> None:
        """同一个客户端的连续读取应复用未过期的应用凭证。"""

        requester = FakeRequester(
            [{"code": 0, "data": {"items": [], "has_more": False}}]
        )
        client = LarkBaseMappingClient(self.config, requester=requester)

        client.list_spu_sku_mappings("10001")
        client.list_spu_sku_mappings("10002")

        token_calls = [call for call in requester.calls if call[0] == "POST"]
        self.assertEqual(len(token_calls), 1)

    def test_conflicting_duplicate_mapping_is_rejected(self) -> None:
        """相同 SPU/SKU 对出现不同展示数据时应停止读取。"""

        requester = FakeRequester(
            [
                {
                    "code": 0,
                    "data": {
                        "items": [
                            _record("10001", "10002", "69002", "商品 A", "蓝色 M"),
                            _record("10001", "10002", "69002", "商品 A", "蓝色 L"),
                        ],
                        "has_more": False,
                    },
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "冲突的 SPU/SKU 映射"):
            LarkBaseMappingClient(self.config, requester=requester).list_spu_sku_mappings("10001")

    def test_invalid_spu_is_rejected_before_network_request(self) -> None:
        """非法 SPU 不应触发任何飞书请求。"""

        requester = FakeRequester([])

        with self.assertRaisesRegex(ValueError, "SPU ID"):
            LarkBaseMappingClient(self.config, requester=requester).list_spu_sku_mappings("10001 OR 1=1")
        self.assertEqual(requester.calls, [])

    def test_product_pairs_are_filtered_deduplicated_and_sorted(self) -> None:
        """商品对读取应跳过无效行并按两个 SPU 去重排序。"""

        requester = FakeRequester(
            [
                {
                    "code": 0,
                    "data": {
                        "items": [
                            {"record_id": "rec-2", "fields": {"本品spu": "10002", "竞品spu": "20002"}},
                            {"record_id": "rec-1", "fields": {"本品spu": "10001", "竞品spu": "20001"}},
                            {"record_id": "rec-dup", "fields": {"本品spu": "10001", "竞品spu": "20001"}},
                            {"record_id": "rec-empty", "fields": {"本品spu": "", "竞品spu": "20003"}},
                            {"record_id": "rec-same", "fields": {"本品spu": "10004", "竞品spu": "10004"}},
                        ],
                        "has_more": False,
                    },
                }
            ]
        )

        pairs = LarkBaseMappingClient(self.config, requester=requester).list_product_pairs()

        self.assertEqual(
            [(pair.self_spu, pair.competitor_spu) for pair in pairs],
            [("10001", "20001"), ("10002", "20002")],
        )
        request_url = requester.calls[-1][1]
        self.assertIn("/tables/tblPair123/records", request_url)
        self.assertNotIn("filter", parse_qs(urlparse(request_url).query))


class LarkBaseConfigLoadingTest(unittest.TestCase):
    """验证容器进程环境可以直接提供飞书配置。"""

    def test_default_missing_env_file_uses_process_environment_silently(self) -> None:
        """默认环境文件不存在时不应产生无意义的容器警告。"""

        logger = Mock()
        environment = {
            "LARK_APP_ID": "test-app",
            "LARK_APP_SECRET": "test-secret",
            "LARK_BASE_TOKEN": "baseToken123",
            "LARK_TABLE_ID": "tblMapping123",
            "LARK_PAIR_TABLE_ID": "tblPair123",
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            environment,
            clear=False,
        ), patch(
            "jd_competitor_analysis.lark_mapping.PROJECT_ROOT",
            Path(temp_dir),
        ), patch(
            "jd_competitor_analysis.lark_mapping.LOGGER",
            logger,
        ):
            config = load_lark_base_config()

        self.assertEqual(config.app_id, "test-app")
        self.assertEqual(config.pair_table_id, "tblPair123")
        logger.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
