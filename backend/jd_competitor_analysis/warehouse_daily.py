"""读取并组装可重复使用的数仓标准化日数据。"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from sqlalchemy.engine import Engine

from .lark_mapping import LarkBaseMappingClient, SkuMapping, load_lark_base_config
from .warehouse import create_warehouse_engine, load_warehouse_config
from .warehouse_normalization import normalize_daily_dataset
from .warehouse_sources import ProductPair, read_competitor_sources, read_self_sku_daily


LOGGER = logging.getLogger(__name__)


def build_daily_dataset(
    engine: Engine,
    product_pair: ProductPair,
    report_date: str,
    mapping_client: LarkBaseMappingClient | None,
    mappings_override: list[SkuMapping] | None = None,
) -> dict[str, Any]:
    """从外部来源生成完整标准化日数据。

    功能说明：先读取五张竞品表并校验核心记录，再读取飞书 SKU 映射和本品 SKU 日数据，最后调用纯转换函数组装稳定事实对象。
    参数 engine：已配置的 StarRocks SQLAlchemy 引擎。
    参数 product_pair：当前本品与竞品 SPU 商品对。
    参数 report_date：业务日期，格式为 `YYYY-MM-DD`。
    参数 mapping_client：飞书 SPU/SKU 映射只读客户端；提供覆盖映射时允许为空。
    参数 mappings_override：排查或测试时显式提供的 SKU 映射；为空时实时读取飞书。
    返回值：可持久化到 `analysis_datasets.payload_json` 的完整标准化日数据。
    """

    LOGGER.info(
        "开始构建完整日数据：date=%s，compare_number=%s",
        report_date,
        product_pair.compare_number,
    )
    raw_sources = read_competitor_sources(engine, product_pair, report_date)
    if not raw_sources["core_metrics"]:
        raise LookupError(
            f"核心指标表没有商品对日数据：date={report_date}，compare_number={product_pair.compare_number}"
        )
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
        "完整日数据构建完成：date=%s，compare_number=%s，status=%s",
        report_date,
        product_pair.compare_number,
        result["quality"]["status"],
    )
    return result


def run_warehouse_daily_check(args: Any) -> None:
    """执行完整日数据只读检查。

    功能说明：加载数仓和飞书配置，构建指定商品对的标准化日数据，并输出来源、SKU 汇总和质量摘要。
    参数 args：命令行参数，包含 env_file、date、compare_number 和可选 sku_id。
    返回值：无；标准化日数据摘要写入标准输出。
    """

    config = load_warehouse_config(args.env_file)
    engine = create_warehouse_engine(config)
    product_pair = ProductPair.parse(args.compare_number)
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
            "compare_number": product_pair.compare_number,
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
