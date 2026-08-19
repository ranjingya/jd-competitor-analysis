"""编排数仓日数据、固定公式、报告和 AI 任务。"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.engine import Engine

from jd_competitor_analysis.lark_mapping import LarkBaseMappingClient, load_lark_base_config
from jd_competitor_analysis.product_assets import load_product_images
from jd_competitor_analysis.warehouse import create_warehouse_engine, load_warehouse_config
from jd_competitor_analysis.warehouse_analysis import analyze_daily_dataset, build_ai_task_payload
from jd_competitor_analysis.warehouse_daily import build_daily_dataset
from jd_competitor_analysis.warehouse_sources import ProductPair, parse_report_date

from ..config import get_settings
from ..database import Database
from ..repositories.dataset_repository import DatasetRepository
from ..repositories.report_repository import ReportRepository
from ..repositories.task_repository import TaskRepository
from .analysis import enqueue_ai_analysis, persist_base_report, persist_daily_dataset


LOGGER = logging.getLogger(__name__)
CONCURRENCY_LIMIT_PATTERN = re.compile(r"Exceed concurrency limit:\s*(\d+)", re.IGNORECASE)


def _processing_error_message(error: Exception) -> tuple[str, bool]:
    """把底层异常转换为适合命令行展示的简洁信息。

    功能说明：识别数仓并发限制等可重试错误，避免把完整 SQL 和参数写入默认日志；
    未识别错误保留异常首行，完整堆栈交给 DEBUG 日志。
    参数 error：商品对处理流程抛出的原始异常。
    返回值：由简洁错误信息和是否建议重试组成的二元组。
    """

    error_text = str(error)
    concurrency_match = CONCURRENCY_LIMIT_PATTERN.search(error_text)
    if concurrency_match:
        limit = concurrency_match.group(1)
        return f"数仓查询并发已达到上限 {limit}，请稍后重试", True
    first_line = next((line.strip() for line in error_text.splitlines() if line.strip()), "")
    message = first_line or error.__class__.__name__
    return message[:500], False


def process_daily_pair(
    engine: Engine,
    mapping_client: LarkBaseMappingClient,
    product_pair: ProductPair,
    report_date: str,
    dataset_repository: DatasetRepository,
    report_repository: ReportRepository,
    task_repository: TaskRepository,
    title: str | None = None,
    product_images: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """处理一天的一组本品与竞品。

    功能说明：读取并标准化外部数据，写入不可变数据集，执行固定公式，保存基础报告并创建 AI 任务；无效数据只保留数据集。
    参数 engine：StarRocks SQLAlchemy 引擎。
    参数 mapping_client：飞书商品对和 SPU/SKU 映射只读客户端。
    参数 product_pair：当前本品和竞品 SPU。
    参数 report_date：业务日期，格式为 `YYYY-MM-DD`。
    参数 dataset_repository：标准化数据集仓库。
    参数 report_repository：看板报告仓库。
    参数 task_repository：AI 任务仓库。
    参数 title：可选看板标题。
    参数 product_images：可选商品主图索引。
    返回值：包含处理状态和三个持久化 ID 的摘要。
    """

    selected_date = parse_report_date(report_date).isoformat()
    LOGGER.info(
        "开始处理商品对：date=%s，compare_number=%s",
        selected_date,
        product_pair.compare_number,
    )
    dataset = build_daily_dataset(
        engine,
        product_pair,
        selected_date,
        mapping_client,
    )
    dataset_id = persist_daily_dataset(dataset_repository, dataset)
    quality_status = str(dataset["quality"]["status"])
    if quality_status == "invalid":
        LOGGER.warning(
            "数据集质量无效，仅保留数据集：dataset_id=%s，compare_number=%s",
            dataset_id,
            product_pair.compare_number,
        )
        return {
            "compare_number": product_pair.compare_number,
            "status": "invalid",
            "quality_status": quality_status,
            "dataset_id": dataset_id,
            "report_id": None,
            "analysis_id": None,
        }

    report = analyze_daily_dataset(dataset, title=title, product_images=product_images)
    report_id = persist_base_report(report_repository, dataset_id, report)
    task_payload = build_ai_task_payload(dataset_id, dataset, report)
    analysis_id = enqueue_ai_analysis(task_repository, dataset_id, task_payload)
    LOGGER.info(
        "商品对日分析入库完成：dataset_id=%s，report_id=%s，analysis_id=%s",
        dataset_id,
        report_id,
        analysis_id,
    )
    return {
        "compare_number": product_pair.compare_number,
        "status": "pending_ai",
        "quality_status": quality_status,
        "dataset_id": dataset_id,
        "report_id": report_id,
        "analysis_id": analysis_id,
    }


def process_daily_pairs(
    engine: Engine,
    mapping_client: LarkBaseMappingClient,
    product_pairs: Iterable[ProductPair],
    report_date: str,
    database: Database,
    title: str | None = None,
    product_images: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """顺序处理一天的多组商品对。

    功能说明：复用一个数仓连接池、飞书客户端和统一数据库，核心表缺数时按业务规则跳过，其他异常记录失败后继续下一组。
    参数 engine：StarRocks SQLAlchemy 引擎。
    参数 mapping_client：飞书只读客户端。
    参数 product_pairs：需要顺序处理的商品对。
    参数 report_date：业务日期。
    参数 database：统一 Backend 数据库。
    参数 title：可选看板标题。
    参数 product_images：可选商品主图索引。
    返回值：每个商品对的处理摘要。
    """

    dataset_repository = DatasetRepository(database)
    report_repository = ReportRepository(database)
    task_repository = TaskRepository(database)
    results = []
    for product_pair in product_pairs:
        try:
            result = process_daily_pair(
                engine,
                mapping_client,
                product_pair,
                report_date,
                dataset_repository,
                report_repository,
                task_repository,
                title=title,
                product_images=product_images,
            )
        except LookupError as error:
            LOGGER.warning("商品对在核心指标表中不存在，跳过：%s", error)
            result = {
                "compare_number": product_pair.compare_number,
                "status": "skipped",
                "quality_status": None,
                "dataset_id": None,
                "report_id": None,
                "analysis_id": None,
                "message": str(error),
            }
        except Exception as error:
            message, retryable = _processing_error_message(error)
            LOGGER.error(
                "商品对处理失败%s：compare_number=%s，原因=%s",
                "（可重试）" if retryable else "",
                product_pair.compare_number,
                message,
            )
            LOGGER.debug(
                "商品对处理失败堆栈：compare_number=%s",
                product_pair.compare_number,
                exc_info=True,
            )
            result = {
                "compare_number": product_pair.compare_number,
                "status": "failed",
                "quality_status": None,
                "dataset_id": None,
                "report_id": None,
                "analysis_id": None,
                "message": message,
                "retryable": retryable,
            }
        results.append(result)
    return results


def _selected_pairs(
    mapping_client: LarkBaseMappingClient,
    compare_numbers: list[str],
) -> list[ProductPair]:
    """解析命令行商品对或从飞书读取候选。"""

    if compare_numbers:
        pairs = [ProductPair.parse(value) for value in compare_numbers]
    else:
        pairs = [ProductPair(item.self_spu, item.competitor_spu) for item in mapping_client.list_product_pairs()]
    unique_pairs = {pair.compare_number: pair for pair in pairs}
    return list(unique_pairs.values())


def run_warehouse_daily_analysis(args: Any) -> None:
    """执行一天的正式数仓分析入库命令。

    功能说明：从环境变量创建只读外部连接和统一数据库，处理指定或飞书配置的商品对，并向标准输出写入摘要。
    参数 args：包含 env_file、date、compare_number 和 title 的命令行参数。
    返回值：无；处理摘要写入标准输出，存在失败商品对时抛出异常使命令返回非零状态。
    """

    warehouse_config = load_warehouse_config(args.env_file)
    lark_config = load_lark_base_config(args.env_file)
    engine = create_warehouse_engine(warehouse_config)
    mapping_client = LarkBaseMappingClient(lark_config)
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    try:
        product_pairs = _selected_pairs(mapping_client, list(args.compare_number or []))
        if not product_pairs:
            raise ValueError("没有可处理的飞书商品对")
        results = process_daily_pairs(
            engine,
            mapping_client,
            product_pairs,
            args.date,
            database,
            title=args.title,
            product_images=load_product_images(),
        )
    finally:
        engine.dispose()

    summary = {
        "date": parse_report_date(args.date).isoformat(),
        "database_path": str(Path(settings.database_path)),
        "counts": {
            status: sum(item["status"] == status for item in results)
            for status in ("pending_ai", "invalid", "skipped", "failed")
        },
        "results": results,
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    failed_count = summary["counts"]["failed"]
    if failed_count:
        failed_messages = "；".join(
            f"{item['compare_number']}：{item.get('message') or '未知错误'}"
            for item in results
            if item["status"] == "failed"
        )
        raise RuntimeError(f"有 {failed_count} 个商品对处理失败：{failed_messages}")
