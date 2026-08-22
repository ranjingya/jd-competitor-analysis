"""编排数仓日数据、固定公式、DeepSeek 分析和报告。"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Protocol

from sqlalchemy.engine import Engine

from jd_competitor_analysis.lark_mapping import LarkBaseMappingClient, load_lark_base_config
from jd_competitor_analysis.product_assets import load_product_images
from jd_competitor_analysis.warehouse import create_warehouse_engine, load_warehouse_config
from jd_competitor_analysis.warehouse_analysis import analyze_daily_dataset, build_ai_task_payload
from jd_competitor_analysis.warehouse_daily import build_daily_dataset
from jd_competitor_analysis.warehouse_sources import ProductPair, parse_report_date

from ..config import get_settings
from ..database import Database
from ..deepseek_analysis import DeepSeekAnalysisConfig, DeepSeekAnalyzer
from ..job_lock import acquire_job_lock
from ..repositories.dataset_repository import DatasetRepository
from ..repositories.report_repository import ReportRepository
from ..repositories.task_repository import TaskRepository
from .analysis import persist_base_report, persist_daily_dataset, start_ai_analysis


LOGGER = logging.getLogger(__name__)
CONCURRENCY_LIMIT_PATTERN = re.compile(r"Exceed concurrency limit:\s*(\d+)", re.IGNORECASE)


class AIAnalyzer(Protocol):
    """约束日分析流程需要的模型能力。"""

    model: str
    analysis_version: str
    prompt_hash: str

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        """根据确定性事实生成 AI 字段。"""


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
    ai_analyzer: AIAnalyzer,
    title: str | None = None,
    product_images: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """处理一天的一组本品与竞品。

    功能说明：读取并标准化外部数据，执行固定公式，调用 DeepSeek 并合并完整报告；无效数据只保留数据集。
    参数 engine：StarRocks SQLAlchemy 引擎。
    参数 mapping_client：飞书商品对和 SPU/SKU 映射只读客户端。
    参数 product_pair：当前本品和竞品 SPU。
    参数 report_date：业务日期，格式为 `YYYY-MM-DD`。
    参数 dataset_repository：标准化数据集仓库。
    参数 report_repository：看板报告仓库。
    参数 task_repository：内部 AI 执行记录仓库。
    参数 ai_analyzer：根据确定性事实生成 AI 字段的分析器。
    参数 title：可选看板标题。
    参数 product_images：可选商品主图索引。
    返回值：包含处理状态和三个持久化 ID 的摘要。
    """

    started_at = perf_counter()
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
            "数据集质量无效，仅保留数据集：dataset_id=%s，compare_number=%s，耗时=%.3fs",
            dataset_id,
            product_pair.compare_number,
            perf_counter() - started_at,
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
    task_payload = build_ai_task_payload(dataset, report)
    start_result = start_ai_analysis(
        task_repository,
        report_id,
        task_payload,
        ai_analyzer.model,
        ai_analyzer.analysis_version,
        ai_analyzer.prompt_hash,
    )
    analysis_id = start_result.analysis_id
    if not start_result.should_execute:
        LOGGER.info(
            "商品对日分析复用已完成 AI 结果：report_id=%s，analysis_id=%s，耗时=%.3fs",
            report_id,
            analysis_id,
            perf_counter() - started_at,
        )
        return {
            "compare_number": product_pair.compare_number,
            "status": "ready",
            "quality_status": quality_status,
            "dataset_id": dataset_id,
            "report_id": report_id,
            "analysis_id": analysis_id,
            "reused": True,
        }

    report_repository.activate_pending(report_id, dataset_id, report)
    try:
        ai_result = ai_analyzer.analyze(task_payload)
        task_repository.complete(analysis_id, ai_result)
    except Exception as error:
        message, _ = _processing_error_message(error)
        task_repository.fail(analysis_id, message)
        LOGGER.error(
            "商品对 AI 分析失败：compare_number=%s，analysis_id=%s，原因=%s，耗时=%.3fs",
            product_pair.compare_number,
            analysis_id,
            message,
            perf_counter() - started_at,
        )
        LOGGER.debug("商品对 AI 分析失败堆栈：analysis_id=%s", analysis_id, exc_info=True)
        return {
            "compare_number": product_pair.compare_number,
            "status": "ai_failed",
            "quality_status": quality_status,
            "dataset_id": dataset_id,
            "report_id": report_id,
            "analysis_id": analysis_id,
            "message": message,
        }
    LOGGER.info(
        "商品对日分析完成：dataset_id=%s，report_id=%s，analysis_id=%s，耗时=%.3fs",
        dataset_id,
        report_id,
        analysis_id,
        perf_counter() - started_at,
    )
    return {
        "compare_number": product_pair.compare_number,
        "status": "ready",
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
    ai_analyzer: AIAnalyzer,
    title: str | None = None,
    product_images: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """顺序处理一天的多组商品对。

    功能说明：复用一个数仓连接池、飞书客户端、模型分析器和统一数据库，逐个串行完成商品对；单项异常不影响后续商品对。
    参数 engine：StarRocks SQLAlchemy 引擎。
    参数 mapping_client：飞书只读客户端。
    参数 product_pairs：需要顺序处理的商品对。
    参数 report_date：业务日期。
    参数 database：统一 Backend 数据库。
    参数 ai_analyzer：DeepSeek 分析器。
    参数 title：可选看板标题。
    参数 product_images：可选商品主图索引。
    返回值：每个商品对的处理摘要。
    """

    dataset_repository = DatasetRepository(database)
    report_repository = ReportRepository(database)
    task_repository = TaskRepository(database)
    results = []
    for product_pair in product_pairs:
        pair_started_at = perf_counter()
        try:
            result = process_daily_pair(
                engine,
                mapping_client,
                product_pair,
                report_date,
                dataset_repository,
                report_repository,
                task_repository,
                ai_analyzer,
                title=title,
                product_images=product_images,
            )
        except LookupError as error:
            LOGGER.warning(
                "商品对在核心指标表中不存在，跳过：%s，耗时=%.3fs",
                error,
                perf_counter() - pair_started_at,
            )
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
                "商品对处理失败%s：compare_number=%s，原因=%s，耗时=%.3fs",
                "（可重试）" if retryable else "",
                product_pair.compare_number,
                message,
                perf_counter() - pair_started_at,
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


def _selected_report_date(args: Any) -> str:
    """解析日任务的业务日期。

    功能说明：支持显式日期与按服务器本地日期计算昨天，两者由命令行互斥参数保证唯一。
    参数 args：包含 date 和 yesterday 的命令行参数。
    返回值：格式为 YYYY-MM-DD 的业务日期。
    """

    if getattr(args, "yesterday", False):
        return (date.today() - timedelta(days=1)).isoformat()
    return parse_report_date(args.date).isoformat()


def run_warehouse_daily_analysis(args: Any) -> None:
    """执行一天的正式数仓分析入库命令。

    功能说明：持有进程锁后创建只读外部连接、DeepSeek 分析器和统一数据库，顺序处理商品对并输出摘要。
    参数 args：包含 env_file、date 或 yesterday、compare_number 和 title 的命令行参数。
    返回值：无；处理摘要写入标准输出，存在失败商品对时抛出异常使命令返回非零状态。
    """

    settings = get_settings()
    selected_date = _selected_report_date(args)
    with acquire_job_lock(settings.analysis_lock_path) as acquired:
        if not acquired:
            summary = {
                "date": selected_date,
                "database_path": str(settings.database_path),
                "status": "already_running",
                "counts": {},
                "results": [],
            }
            sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
            return
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY 尚未配置")
        warehouse_config = load_warehouse_config(args.env_file)
        lark_config = load_lark_base_config(args.env_file)
        ai_analyzer = DeepSeekAnalyzer(
            DeepSeekAnalysisConfig(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
                max_attempts=settings.deepseek_max_attempts,
            )
        )
        database = Database(settings.database_path)
        database.initialize()
        product_images = load_product_images(settings.product_images_path)
        product_images_sync = ReportRepository(database).sync_product_images(product_images)
        engine = create_warehouse_engine(warehouse_config)
        mapping_client = LarkBaseMappingClient(lark_config)
        try:
            product_pairs = _selected_pairs(mapping_client, list(args.compare_number or []))
            if not product_pairs:
                raise ValueError("没有可处理的飞书商品对")
            results = process_daily_pairs(
                engine,
                mapping_client,
                product_pairs,
                selected_date,
                database,
                ai_analyzer,
                title=args.title,
                product_images=product_images,
            )
        finally:
            engine.dispose()

    summary = {
        "date": selected_date,
        "database_path": str(Path(settings.database_path)),
        "product_images_path": str(settings.product_images_path),
        "product_images_sync": product_images_sync,
        "counts": {
            status: sum(item["status"] == status for item in results)
            for status in ("ready", "ai_failed", "invalid", "skipped", "failed")
        },
        "results": results,
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    failed_count = summary["counts"]["failed"] + summary["counts"]["ai_failed"]
    if failed_count:
        failed_messages = "；".join(
            f"{item['compare_number']}：{item.get('message') or '未知错误'}"
            for item in results
            if item["status"] in {"failed", "ai_failed"}
        )
        raise RuntimeError(f"有 {failed_count} 个商品对处理失败：{failed_messages}")
