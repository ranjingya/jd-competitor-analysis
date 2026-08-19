"""通过飞书应用身份只读获取 SPU/SKU 映射。"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ID_PATTERN = re.compile(r"^[0-9]+$")
BASE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
TABLE_ID_PATTERN = re.compile(r"^tbl[A-Za-z0-9]+$")
LARK_API_BASE_URL = "https://open.feishu.cn/open-apis"
MAPPING_FIELDS = {
    "spu_id": "主商品条码",
    "sku_id": "子商品条码",
    "barcode_69": "69码",
    "product_name": "商品名称",
    "specification": "规格",
}

JsonRequester = Callable[[str, str, dict[str, str], dict[str, Any] | None, int], dict[str, Any]]


@dataclass(frozen=True)
class LarkBaseConfig:
    """保存飞书应用身份和目标多维表参数，敏感字段不参与对象展示。"""

    app_id: str
    app_secret: str = field(repr=False)
    base_token: str = ""
    table_id: str = ""
    request_timeout_seconds: int = 30
    page_size: int = 500
    api_base_url: str = LARK_API_BASE_URL


@dataclass(frozen=True)
class SkuMapping:
    """保存一个 SPU 与一个 SKU 的展示映射。"""

    spu_id: str
    sku_id: str
    barcode_69: str | None
    product_name: str | None
    specification: str | None


def _required_text(name: str) -> str:
    """读取必填文本环境变量。"""

    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"飞书多维表配置缺少：{name}")
    return value


def _positive_integer(name: str, default: int, maximum: int) -> int:
    """读取有上限的正整数环境变量。"""

    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} 必须是正整数：{raw_value}") from error
    if value <= 0 or value > maximum:
        raise ValueError(f"{name} 必须大于 0 且不大于 {maximum}：{value}")
    return value


def load_lark_base_config(env_file: Path | None = None) -> LarkBaseConfig:
    """加载飞书多维表只读配置。

    功能说明：从指定 `.env` 或项目根目录 `.env` 读取应用凭据和目标多维表标识，并完成格式校验。
    参数 env_file：环境变量文件路径；为空时使用项目根目录 `.env`。
    返回值：可用于创建只读飞书多维表客户端的配置对象。
    """

    resolved_env_file = (env_file or PROJECT_ROOT / ".env").expanduser().resolve()
    if resolved_env_file.exists():
        LOGGER.info("加载飞书环境变量：%s", resolved_env_file)
        load_dotenv(resolved_env_file, override=False)
    else:
        LOGGER.warning("环境变量文件不存在，将仅使用进程环境变量：%s", resolved_env_file)

    base_token = _required_text("LARK_BASE_TOKEN")
    table_id = _required_text("LARK_TABLE_ID")
    if not BASE_TOKEN_PATTERN.fullmatch(base_token):
        raise ValueError("LARK_BASE_TOKEN 格式无效")
    if not TABLE_ID_PATTERN.fullmatch(table_id):
        raise ValueError("LARK_TABLE_ID 格式无效")

    return LarkBaseConfig(
        app_id=_required_text("LARK_APP_ID"),
        app_secret=_required_text("LARK_APP_SECRET"),
        base_token=base_token,
        table_id=table_id,
        request_timeout_seconds=_positive_integer("LARK_REQUEST_TIMEOUT", 30, 120),
        page_size=_positive_integer("LARK_PAGE_SIZE", 500, 500),
    )


def _request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    """调用飞书 JSON 接口并解析响应。"""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except TimeoutError as error:
        raise RuntimeError(f"飞书接口读取超时：超过 {timeout_seconds} 秒") from error
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"飞书接口返回 HTTP {error.code}：{error_body}") from error
    except URLError as error:
        raise RuntimeError(f"飞书接口连接失败：{error.reason}") from error

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise RuntimeError("飞书接口返回了无效 JSON") from error
    if not isinstance(result, dict):
        raise RuntimeError("飞书接口响应顶层不是对象")
    return result


def _require_success(result: dict[str, Any], operation: str) -> dict[str, Any]:
    """校验飞书接口业务状态并返回响应数据。"""

    if result.get("code") != 0:
        raise RuntimeError(
            f"{operation}失败：code={result.get('code')}，msg={result.get('msg') or '未知错误'}"
        )
    data = result.get("data")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{operation}响应中的 data 不是对象")
    return data


def _optional_cell_text(value: Any) -> str | None:
    """把多维表普通单元格转换为可为空文本。"""

    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _required_product_id(field_name: str, value: Any) -> str:
    """读取并校验多维表中的商品标识。"""

    text_value = _optional_cell_text(value)
    if text_value is None or not PRODUCT_ID_PATTERN.fullmatch(text_value):
        raise ValueError(f"多维表字段“{field_name}”不是有效商品 ID：{value}")
    return text_value


class LarkBaseMappingClient:
    """使用 tenant_access_token 只读查询飞书多维表映射。"""

    def __init__(self, config: LarkBaseConfig, requester: JsonRequester = _request_json) -> None:
        """初始化只读客户端。

        功能说明：保存飞书应用和目标表配置，并准备进程内 tenant token 缓存。
        参数 config：飞书应用身份与多维表配置。
        参数 requester：执行 JSON HTTP 请求的函数，默认使用标准库网络实现。
        返回值：无。
        """

        self._config = config
        self._requester = requester
        self._tenant_access_token: str | None = None
        self._token_expires_at = 0.0

    def _get_tenant_access_token(self) -> str:
        """获取并缓存飞书应用身份凭证。"""

        now = time.monotonic()
        if self._tenant_access_token and now < self._token_expires_at:
            return self._tenant_access_token

        LOGGER.info("开始获取飞书 tenant_access_token")
        result = self._requester(
            "POST",
            f"{self._config.api_base_url}/auth/v3/tenant_access_token/internal",
            {"Content-Type": "application/json; charset=utf-8"},
            {"app_id": self._config.app_id, "app_secret": self._config.app_secret},
            self._config.request_timeout_seconds,
        )
        if result.get("code") != 0:
            raise RuntimeError(
                f"获取飞书 tenant_access_token 失败：code={result.get('code')}，"
                f"msg={result.get('msg') or '未知错误'}"
            )
        token = _optional_cell_text(result.get("tenant_access_token"))
        if token is None:
            raise RuntimeError("飞书凭证响应缺少 tenant_access_token")
        expire = result.get("expire", 7200)
        try:
            expire_seconds = max(int(expire), 60)
        except (TypeError, ValueError):
            expire_seconds = 7200
        self._tenant_access_token = token
        self._token_expires_at = now + max(expire_seconds - 60, 30)
        LOGGER.info("飞书 tenant_access_token 获取成功")
        return token

    def list_spu_sku_mappings(self, spu_id: str) -> list[SkuMapping]:
        """读取指定 SPU 的全部 SKU 映射。

        功能说明：按主商品条码在服务端筛选记录，分页读取五个业务字段，并校验和去重映射关系。
        参数 spu_id：需要查询的京东 SPU ID。
        返回值：包含 SPU ID、SKU ID、69 码、商品名和规格的映射列表。
        """

        selected_spu_id = str(spu_id).strip()
        if not PRODUCT_ID_PATTERN.fullmatch(selected_spu_id):
            raise ValueError(f"SPU ID 必须是正整数：{spu_id}")

        token = self._get_tenant_access_token()
        endpoint = (
            f"{self._config.api_base_url}/bitable/v1/apps/{self._config.base_token}"
            f"/tables/{self._config.table_id}/records"
        )
        field_names = list(MAPPING_FIELDS.values())
        page_token: str | None = None
        records: list[dict[str, Any]] = []
        LOGGER.info("开始只读查询飞书 SPU/SKU 映射：spu_id=%s", selected_spu_id)

        while True:
            query = {
                "page_size": str(self._config.page_size),
                "field_names": json.dumps(field_names, ensure_ascii=False),
                "filter": f'CurrentValue.[{MAPPING_FIELDS["spu_id"]}]="{selected_spu_id}"',
            }
            if page_token:
                query["page_token"] = page_token
            result = self._requester(
                "GET",
                f"{endpoint}?{urlencode(query)}",
                {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                None,
                self._config.request_timeout_seconds,
            )
            data = _require_success(result, "读取飞书 SPU/SKU 映射")
            items = data.get("items") or []
            if not isinstance(items, list):
                raise RuntimeError("读取飞书 SPU/SKU 映射响应中的 items 不是数组")
            records.extend(item for item in items if isinstance(item, dict))
            if not data.get("has_more"):
                break
            next_page_token = _optional_cell_text(data.get("page_token"))
            if next_page_token is None or next_page_token == page_token:
                raise RuntimeError("飞书多维表分页响应缺少有效的 page_token")
            page_token = next_page_token

        mappings_by_key: dict[tuple[str, str], SkuMapping] = {}
        for record in records:
            fields = record.get("fields")
            if not isinstance(fields, dict):
                raise RuntimeError(f"飞书记录 {record.get('record_id')} 缺少 fields 对象")
            mapping = SkuMapping(
                spu_id=_required_product_id(MAPPING_FIELDS["spu_id"], fields.get(MAPPING_FIELDS["spu_id"])),
                sku_id=_required_product_id(MAPPING_FIELDS["sku_id"], fields.get(MAPPING_FIELDS["sku_id"])),
                barcode_69=_optional_cell_text(fields.get(MAPPING_FIELDS["barcode_69"])),
                product_name=_optional_cell_text(fields.get(MAPPING_FIELDS["product_name"])),
                specification=_optional_cell_text(fields.get(MAPPING_FIELDS["specification"])),
            )
            if mapping.spu_id != selected_spu_id:
                raise ValueError(
                    f"飞书筛选结果包含其他 SPU：期望 {selected_spu_id}，实际 {mapping.spu_id}"
                )
            key = (mapping.spu_id, mapping.sku_id)
            previous = mappings_by_key.get(key)
            if previous is not None and previous != mapping:
                raise ValueError(f"飞书多维表存在冲突的 SPU/SKU 映射：{mapping.spu_id}+{mapping.sku_id}")
            mappings_by_key[key] = mapping

        mappings = sorted(mappings_by_key.values(), key=lambda item: int(item.sku_id))
        LOGGER.info("飞书 SPU/SKU 映射读取完成：spu_id=%s，sku_count=%s", selected_spu_id, len(mappings))
        return mappings


def run_lark_mapping_check(args: Any) -> None:
    """执行飞书 SPU/SKU 映射只读检查。

    功能说明：加载飞书应用配置，读取指定 SPU 的五字段映射，并输出便于人工核对的 JSON。
    参数 args：命令行参数，包含 env_file 和 spu_id。
    返回值：无；映射检查结果写入标准输出。
    """

    config = load_lark_base_config(args.env_file)
    mappings = LarkBaseMappingClient(config).list_spu_sku_mappings(args.spu_id)
    result = {
        "spu_id": str(args.spu_id),
        "sku_count": len(mappings),
        "mappings": [asdict(mapping) for mapping in mappings],
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
