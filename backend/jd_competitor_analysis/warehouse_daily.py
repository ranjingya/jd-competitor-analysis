"""读取并组装可重复使用的数仓标准化日数据。"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy.engine import Engine

from .lark_mapping import LarkBaseMappingClient, SkuMapping, load_lark_base_config
from .warehouse import create_warehouse_engine, load_warehouse_config
from .warehouse_normalization import normalize_daily_dataset
from .warehouse_sources import (
    COMPETITOR_TABLES,
    ProductPair,
    read_competitor_sources,
    read_self_sku_daily,
)


LOGGER = logging.getLogger(__name__)
REQUIRED_PRODUCT_ROLES = {"self", "competitor"}


@dataclass(frozen=True)
class WarehouseDataIncompleteError(LookupError):
    """表示某个商品对在至少一张来源表中缺少本品或竞品记录。"""

    report_date: str
    product_pair: ProductPair
    missing_roles: dict[str, list[str]]

    def __str__(self) -> str:
        """生成不包含业务字段内容的缺失摘要。"""

        details = "，".join(
            f"{source_id}={'+'.join(roles)}"
            for source_id, roles in self.missing_roles.items()
        )
        return (
            f"五张来源表记录不完整：date={self.report_date}，"
            f"self_spu={self.product_pair.self_spu}，"
            f"competitor_spu={self.product_pair.competitor_spu}，missing={details}"
        )


def find_missing_source_roles(
    raw_sources: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    """检查五张来源表是否同时存在本品和竞品记录。

    功能说明：只判断表级商品记录是否存在，不检查记录内部字段、维度和值；字段为
    `null`、`masked` 或 `0` 均不影响完整性。
    参数 raw_sources：按来源 ID 分组的数仓原始记录。
    返回值：缺失来源及对应商品角色；全部完整时返回空字典。
    """

    missing: dict[str, list[str]] = {}
    for source in COMPETITOR_TABLES:
        source_id = source.source_id
        rows = raw_sources.get(source_id, [])
        present_roles = {
            str(row.get("product_role"))
            for row in rows
            if row.get("product_role") in REQUIRED_PRODUCT_ROLES
        }
        missing_roles = sorted(REQUIRED_PRODUCT_ROLES - present_roles)
        if missing_roles:
            missing[source_id] = missing_roles
    return missing


def build_daily_dataset(
    engine: Engine,
    product_pair: ProductPair,
    report_date: str,
    mapping_client: LarkBaseMappingClient | None,
    mappings_override: list[SkuMapping] | None = None,
) -> dict[str, Any]:
    """从外部来源生成完整标准化日数据。

    功能说明：先读取五张竞品表并校验每张表都包含本品和竞品记录，再读取飞书 SKU 映射和本品 SKU 日数据，最后调用纯转换函数组装稳定事实对象。
    参数 engine：已配置的 StarRocks SQLAlchemy 引擎。
    参数 product_pair：当前本品与竞品 SPU 商品对。
    参数 report_date：业务日期，格式为 `YYYY-MM-DD`。
    参数 mapping_client：飞书 SPU/SKU 映射只读客户端；提供覆盖映射时允许为空。
    参数 mappings_override：排查或测试时显式提供的 SKU 映射；为空时实时读取飞书。
    返回值：可按来源模块持久化到 `analysis_datasets` 的完整标准化日数据。
    """

    started_at = perf_counter()
    LOGGER.info(
        "开始构建完整日数据：date=%s，self_spu=%s，competitor_spu=%s",
        report_date,
        product_pair.self_spu,
        product_pair.competitor_spu,
    )
    raw_sources = read_competitor_sources(engine, product_pair, report_date)
    missing_roles = find_missing_source_roles(raw_sources)
    if missing_roles:
        raise WarehouseDataIncompleteError(report_date, product_pair, missing_roles)
    if mappings_override is not None:
        mappings = list(mappings_override)
        LOGGER.warning("使用显式 SKU 映射覆盖飞书读取：sku_count=%s", len(mappings))
    else:
        if mapping_client is None:
            raise ValueError("未提供飞书映射客户端或显式 SKU 映射")
        mappings = mapping_client.list_spu_sku_mappings(product_pair.self_spu)
    sku_rows = (
        read_self_sku_daily(engine, report_date, [mapping.sku_id for mapping in mappings])
        if mappings
        else []
    )
    result = normalize_daily_dataset(raw_sources, product_pair, report_date, mappings, sku_rows)
    LOGGER.info(
        "完整日数据构建完成：date=%s，self_spu=%s，competitor_spu=%s，status=%s，耗时=%.3fs",
        report_date,
        product_pair.self_spu,
        product_pair.competitor_spu,
        result["quality"]["status"],
        perf_counter() - started_at,
    )
    return result


def run_warehouse_daily_check(args: Any) -> None:
    """执行完整日数据只读检查。

    功能说明：加载数仓和飞书配置，构建指定商品对的标准化日数据，并输出来源、SKU 汇总和质量摘要。
    参数 args：命令行参数，包含 env_file、date、self_spu、competitor_spu 和可选 sku_id。
    返回值：无；标准化日数据摘要写入标准输出。
    """

    config = load_warehouse_config(args.env_file)
    engine = create_warehouse_engine(config)
    product_pair = ProductPair(args.self_spu, args.competitor_spu)
    try:
        if args.sku_id:
            mappings_override = [
                SkuMapping(
                    spu_id=product_pair.self_spu,
                    sku_id=str(sku_id),
                    barcode_69=None,
                    product_name=None,
                    specification=None,
                )
                for sku_id in args.sku_id
            ]
            mapping_client = None
        else:
            mappings_override = None
            mapping_client = LarkBaseMappingClient(load_lark_base_config(args.env_file))
        dataset = build_daily_dataset(
            engine,
            product_pair,
            args.date,
            mapping_client,
            mappings_override=mappings_override,
        )
        self_product = dataset["self_product"]
        summary = {
            "date": dataset["report_date"],
            "self_spu": product_pair.self_spu,
            "competitor_spu": product_pair.competitor_spu,
            "quality": dataset["quality"]["status"],
            "competitor_sources": {
                source_id: {
                    "records": len(source["records"]),
                    "quality": source["quality"]["status"],
                }
                for source_id, source in dataset["sources"].items()
            },
            "self_product": {
                "quality": self_product["quality"]["status"],
                "mapped_sku_count": self_product["quality"]["mapped_sku_count"],
                "warehouse_sku_count": self_product["quality"]["warehouse_sku_count"],
                "missing_sku_ids": self_product["quality"]["missing_sku_ids"],
                "spu_daily_metrics": self_product["spu_daily_metrics"],
            },
        }
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    finally:
        engine.dispose()
