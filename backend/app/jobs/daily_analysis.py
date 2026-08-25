"""编排数仓日数据、固定公式、DeepSeek 分析和报告。"""

from __future__ import annotations

import json
import logging
import random
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Protocol

from sqlalchemy.engine import Engine

from jd_competitor_analysis.lark_mapping import LarkBaseMappingClient, load_lark_base_config
from jd_competitor_analysis.product_assets import load_product_images
from jd_competitor_analysis.warehouse import create_warehouse_engine, load_warehouse_config
from jd_competitor_analysis.warehouse_analysis import analyze_daily_dataset, build_ai_task_payload
from jd_competitor_analysis.warehouse_daily import (
    WarehouseDataIncompleteError,
    build_daily_dataset,
)
from jd_competitor_analysis.warehouse_sources import ProductPair, parse_report_date

from ..config import get_settings
from ..database import Database
from ..job_status import DailyAnalysisStatusWriter
from ..deepseek_analysis import DeepSeekAnalysisConfig, DeepSeekAnalyzer
from ..job_lock import acquire_job_lock
from ..repositories.dataset_repository import DatasetRepository
from ..repositories.report_repository import ReportRepository
from ..repositories.task_repository import TaskRepository
from .analysis import persist_base_report, persist_daily_dataset, start_ai_analysis


LOGGER = logging.getLogger(__name__)
CONCURRENCY_LIMIT_PATTERN = re.compile(r"Exceed concurrency limit:\s*(\d+)", re.IGNORECASE)
CONCURRENCY_RETRY_DELAYS = (30, 60, 120)
CONCURRENCY_RETRY_JITTER_SECONDS = 10
CONCURRENCY_EXHAUSTED_EXIT_CODE = 11
ALREADY_RUNNING_EXIT_CODE = 12
DAILY_REPAIR_WINDOW_DAYS = 7
PairProgressCallback = Callable[[str, ProductPair], None]


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
    progress_callback: PairProgressCallback | None = None,
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
    参数 progress_callback：可选商品对阶段进度回调。
    返回值：包含处理状态和三个持久化 ID 的摘要。
    """

    started_at = perf_counter()
    selected_date = parse_report_date(report_date).isoformat()
    LOGGER.info(
        "开始处理商品对：date=%s，self_spu=%s，competitor_spu=%s",
        selected_date,
        product_pair.self_spu,
        product_pair.competitor_spu,
    )
    if progress_callback is not None:
        progress_callback("warehouse_read", product_pair)
    dataset = build_daily_dataset(
        engine,
        product_pair,
        selected_date,
        mapping_client,
    )
    if progress_callback is not None:
        progress_callback("dataset_persist", product_pair)
    dataset_id = persist_daily_dataset(dataset_repository, dataset)
    quality_status = str(dataset["quality"]["status"])
    if quality_status == "invalid":
        LOGGER.warning(
            "数据集质量无效，仅保留数据集：dataset_id=%s，self_spu=%s，competitor_spu=%s，耗时=%.3fs",
            dataset_id,
            product_pair.self_spu,
            product_pair.competitor_spu,
            perf_counter() - started_at,
        )
        return {
            "self_spu": product_pair.self_spu,
            "competitor_spu": product_pair.competitor_spu,
            "status": "invalid",
            "quality_status": quality_status,
            "dataset_id": dataset_id,
            "report_id": None,
            "analysis_id": None,
        }

    if progress_callback is not None:
        progress_callback("deterministic_analysis", product_pair)
    report = analyze_daily_dataset(dataset, title=title, product_images=product_images)
    report_id = persist_base_report(report_repository, dataset_id, report)
    if progress_callback is not None:
        progress_callback("ai_prepare", product_pair)
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
            "self_spu": product_pair.self_spu,
            "competitor_spu": product_pair.competitor_spu,
            "status": "ready",
            "quality_status": quality_status,
            "dataset_id": dataset_id,
            "report_id": report_id,
            "analysis_id": analysis_id,
            "reused": True,
        }

    report_repository.activate_pending(report_id, dataset_id, report)
    try:
        if progress_callback is not None:
            progress_callback("deepseek_analysis", product_pair)
        ai_result = ai_analyzer.analyze(task_payload)
        if progress_callback is not None:
            progress_callback("report_finalize", product_pair)
        task_repository.complete(analysis_id, ai_result)
    except Exception as error:
        message, _ = _processing_error_message(error)
        task_repository.fail(analysis_id, message)
        LOGGER.error(
            "商品对 AI 分析失败：self_spu=%s，competitor_spu=%s，analysis_id=%s，原因=%s，耗时=%.3fs",
            product_pair.self_spu,
            product_pair.competitor_spu,
            analysis_id,
            message,
            perf_counter() - started_at,
        )
        LOGGER.debug("商品对 AI 分析失败堆栈：analysis_id=%s", analysis_id, exc_info=True)
        return {
            "self_spu": product_pair.self_spu,
            "competitor_spu": product_pair.competitor_spu,
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
        "self_spu": product_pair.self_spu,
        "competitor_spu": product_pair.competitor_spu,
        "status": "ready",
        "quality_status": quality_status,
        "dataset_id": dataset_id,
        "report_id": report_id,
        "analysis_id": analysis_id,
    }


def _process_daily_pair_safely(
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
    progress_callback: PairProgressCallback | None = None,
) -> dict[str, Any]:
    """执行一个商品对并转换为批处理可识别的结果。

    功能说明：将来源记录缺失、数仓并发上限和普通异常转换为独立状态，保证单项问题
    不会中断后续商品对。
    参数 engine：StarRocks SQLAlchemy 引擎。
    参数 mapping_client：飞书只读客户端。
    参数 product_pair：当前处理的本品与竞品 SPU。
    参数 report_date：业务日期。
    参数 dataset_repository：标准化日数据集仓库。
    参数 report_repository：最终报告仓库。
    参数 task_repository：内部 AI 执行记录仓库。
    参数 ai_analyzer：DeepSeek 分析器。
    参数 title：可选看板标题。
    参数 product_images：可选商品主图索引。
    参数 progress_callback：可选商品对阶段进度回调。
    返回值：当前商品对的状态、日期和持久化摘要。
    """

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
            progress_callback=progress_callback,
        )
    except WarehouseDataIncompleteError as error:
        LOGGER.info(
            "商品对来源记录不完整，保留报告缺口：date=%s，self_spu=%s，"
            "competitor_spu=%s，missing=%s，耗时=%.3fs",
            report_date,
            product_pair.self_spu,
            product_pair.competitor_spu,
            error.missing_roles,
            perf_counter() - pair_started_at,
        )
        result = {
            "self_spu": product_pair.self_spu,
            "competitor_spu": product_pair.competitor_spu,
            "status": "data_incomplete",
            "quality_status": None,
            "dataset_id": None,
            "report_id": None,
            "analysis_id": None,
            "missing_roles": error.missing_roles,
            "message": str(error),
        }
    except Exception as error:
        message, retryable = _processing_error_message(error)
        status = "concurrency" if retryable else "failed"
        LOGGER.error(
            "商品对处理失败%s：date=%s，self_spu=%s，competitor_spu=%s，原因=%s，耗时=%.3fs",
            "（数仓并发）" if retryable else "",
            report_date,
            product_pair.self_spu,
            product_pair.competitor_spu,
            message,
            perf_counter() - pair_started_at,
        )
        LOGGER.debug(
            "商品对处理失败堆栈：date=%s，self_spu=%s，competitor_spu=%s",
            report_date,
            product_pair.self_spu,
            product_pair.competitor_spu,
            exc_info=True,
        )
        result = {
            "self_spu": product_pair.self_spu,
            "competitor_spu": product_pair.competitor_spu,
            "status": status,
            "quality_status": None,
            "dataset_id": None,
            "report_id": None,
            "analysis_id": None,
            "message": message,
            "retryable": retryable,
        }
    result["date"] = report_date
    return result


def process_daily_pairs(
    engine: Engine,
    mapping_client: LarkBaseMappingClient,
    product_pairs: Iterable[ProductPair],
    report_date: str,
    database: Database,
    ai_analyzer: AIAnalyzer,
    title: str | None = None,
    product_images: dict[str, dict[str, Any]] | None = None,
    progress_callback: PairProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """顺序处理一天的多组商品对并定向重试数仓并发异常。

    功能说明：首轮不中断地处理全部商品对，将遇到数仓并发上限的组合放入队列，
    再按 30、60、120 秒和随机抖动执行三轮定向重试。
    参数 engine：StarRocks SQLAlchemy 引擎。
    参数 mapping_client：飞书只读客户端。
    参数 product_pairs：需要顺序处理的商品对。
    参数 report_date：业务日期。
    参数 database：统一 Backend 数据库。
    参数 ai_analyzer：DeepSeek 分析器。
    参数 title：可选看板标题。
    参数 product_images：可选商品主图索引。
    参数 progress_callback：可选商品对阶段进度回调。
    返回值：保持输入商品对顺序的处理摘要。
    """

    selected_pairs = list(product_pairs)
    dataset_repository = DatasetRepository(database)
    report_repository = ReportRepository(database)
    task_repository = TaskRepository(database)
    results_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    pending_pairs: list[ProductPair] = []

    def execute(product_pair: ProductPair, attempt: int) -> dict[str, Any]:
        if progress_callback is not None:
            progress_callback("pair_started", product_pair)
        result = _process_daily_pair_safely(
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
            progress_callback=progress_callback,
        )
        result["attempt"] = attempt
        if result["status"] != "concurrency" and progress_callback is not None:
            progress_callback("pair_completed", product_pair)
        return result

    for product_pair in selected_pairs:
        result = execute(product_pair, 1)
        key = (product_pair.self_spu, product_pair.competitor_spu)
        results_by_pair[key] = result
        if result["status"] == "concurrency":
            pending_pairs.append(product_pair)

    for retry_index, delay_seconds in enumerate(CONCURRENCY_RETRY_DELAYS, start=1):
        if not pending_pairs:
            break
        jitter_seconds = random.uniform(0, CONCURRENCY_RETRY_JITTER_SECONDS)
        wait_seconds = delay_seconds + jitter_seconds
        LOGGER.warning(
            "数仓并发商品对准备定向重试：date=%s，retry=%s/%s，pairs=%s，等待=%.1fs",
            report_date,
            retry_index,
            len(CONCURRENCY_RETRY_DELAYS),
            len(pending_pairs),
            wait_seconds,
        )
        time.sleep(wait_seconds)
        next_pending = []
        for product_pair in pending_pairs:
            result = execute(product_pair, retry_index + 1)
            key = (product_pair.self_spu, product_pair.competitor_spu)
            results_by_pair[key] = result
            if result["status"] == "concurrency":
                next_pending.append(product_pair)
        pending_pairs = next_pending

    for product_pair in pending_pairs:
        key = (product_pair.self_spu, product_pair.competitor_spu)
        result = results_by_pair[key]
        result["status"] = "concurrency_exhausted"
        result["retryable"] = False
        if progress_callback is not None:
            progress_callback("pair_completed", product_pair)
        LOGGER.error(
            "数仓并发重试已耗尽：date=%s，self_spu=%s，competitor_spu=%s，attempts=%s",
            report_date,
            product_pair.self_spu,
            product_pair.competitor_spu,
            result["attempt"],
        )

    return [
        results_by_pair[(product_pair.self_spu, product_pair.competitor_spu)]
        for product_pair in selected_pairs
    ]


def _selected_pairs(
    mapping_client: LarkBaseMappingClient,
    self_spu: str | None,
    competitor_spu: str | None,
) -> list[ProductPair]:
    """解析命令行 SPU 或从飞书读取候选商品对。"""

    if bool(self_spu) != bool(competitor_spu):
        raise ValueError("--self-spu 和 --competitor-spu 必须同时提供")
    if self_spu and competitor_spu:
        pairs = [ProductPair(self_spu, competitor_spu)]
    else:
        pairs = [ProductPair(item.self_spu, item.competitor_spu) for item in mapping_client.list_product_pairs()]
    unique_pairs = {(pair.self_spu, pair.competitor_spu): pair for pair in pairs}
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


def _selected_report_dates(args: Any, selected_date: str) -> list[str]:
    """生成当前任务需要检查的日报日期。

    功能说明：显式日期只处理当天；服务器 `--yesterday` 任务处理昨天，并按由近到远
    的顺序检查此前六天报告缺口。
    参数 args：包含 yesterday 标记的命令行参数。
    参数 selected_date：当前主业务日期，格式为 YYYY-MM-DD。
    返回值：主日期在首位、最多七天的业务日期列表。
    """

    if not getattr(args, "yesterday", False):
        return [selected_date]
    primary_date = date.fromisoformat(selected_date)
    return [
        (primary_date - timedelta(days=offset)).isoformat()
        for offset in range(DAILY_REPAIR_WINDOW_DAYS)
    ]


def _existing_report_result(
    report_date: str,
    product_pair: ProductPair,
    report: dict[str, Any],
) -> dict[str, Any]:
    """生成已有完整日报的跳过摘要。"""

    return {
        "date": report_date,
        "self_spu": product_pair.self_spu,
        "competitor_spu": product_pair.competitor_spu,
        "status": "existing",
        "quality_status": None,
        "dataset_id": report.get("dataset_id"),
        "report_id": report.get("report_id"),
        "analysis_id": None,
        "attempt": 0,
    }


def run_warehouse_daily_analysis(args: Any) -> None:
    """执行正式数仓日报分析和最近七天缺口修复。

    功能说明：持有进程锁后处理主业务日期；`--yesterday` 模式同时检查最近七天，
    跳过已有完整日报，只对报告缺口重新读取数仓并生成报告。
    参数 args：包含 env_file、date 或 yesterday、self_spu、competitor_spu 和 title 的命令行参数。
    返回值：无；普通失败抛出异常，数仓并发或进程锁冲突使用专用退出码。
    """

    settings = get_settings()
    selected_date = _selected_report_date(args)
    selected_dates = _selected_report_dates(args, selected_date)
    status_writer = DailyAnalysisStatusWriter(settings.analysis_status_path)
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
            raise SystemExit(ALREADY_RUNNING_EXIT_CODE)

        status_writer.start(selected_date, selected_dates)
        try:
            status_writer.progress("loading_configuration")
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
            report_repository = ReportRepository(database)
            product_images_sync = report_repository.sync_product_images(product_images)
            engine = create_warehouse_engine(warehouse_config)
            mapping_client = LarkBaseMappingClient(lark_config)
            try:
                status_writer.progress("loading_product_pairs")
                product_pairs = _selected_pairs(
                    mapping_client,
                    args.self_spu,
                    args.competitor_spu,
                )
                if not product_pairs:
                    raise ValueError("没有可处理的飞书商品对")
                total_items = len(selected_dates) * len(product_pairs)
                completed_items = 0
                results = []
                status_writer.progress(
                    "checking_reports",
                    completed_items=completed_items,
                    total_items=total_items,
                )
                skip_ready_reports = bool(getattr(args, "yesterday", False))
                for report_date in selected_dates:
                    pending_pairs = []
                    status_writer.progress(
                        "checking_reports",
                        current_date=report_date,
                        completed_items=completed_items,
                        total_items=total_items,
                    )
                    for product_pair in product_pairs:
                        existing = (
                            report_repository.find_ready_day_report(
                                report_date,
                                product_pair.self_spu,
                                product_pair.competitor_spu,
                            )
                            if skip_ready_reports
                            else None
                        )
                        if existing is not None:
                            results.append(
                                _existing_report_result(
                                    report_date,
                                    product_pair,
                                    existing,
                                )
                            )
                            completed_items += 1
                            status_writer.progress(
                                "report_existing",
                                current_date=report_date,
                                self_spu=product_pair.self_spu,
                                competitor_spu=product_pair.competitor_spu,
                                completed_items=completed_items,
                                total_items=total_items,
                            )
                            continue
                        pending_pairs.append(product_pair)
                    LOGGER.info(
                        "日报日期检查完成：date=%s，pairs=%s，pending=%s，existing=%s",
                        report_date,
                        len(product_pairs),
                        len(pending_pairs),
                        len(product_pairs) - len(pending_pairs),
                    )
                    if pending_pairs:

                        def record_pair_progress(
                            stage: str,
                            product_pair: ProductPair,
                        ) -> None:
                            """把商品对阶段转换为当前批次的持久化进度。"""

                            nonlocal completed_items
                            if stage == "pair_completed":
                                completed_items += 1
                            status_writer.progress(
                                stage,
                                current_date=report_date,
                                self_spu=product_pair.self_spu,
                                competitor_spu=product_pair.competitor_spu,
                                completed_items=completed_items,
                                total_items=total_items,
                            )

                        results.extend(
                            process_daily_pairs(
                                engine,
                                mapping_client,
                                pending_pairs,
                                report_date,
                                database,
                                ai_analyzer,
                                title=getattr(args, "title", None),
                                product_images=product_images,
                                progress_callback=record_pair_progress,
                            )
                        )
            finally:
                engine.dispose()

            summary = {
                "date": selected_date,
                "dates": selected_dates,
                "database_path": str(Path(settings.database_path)),
                "product_images_path": str(settings.product_images_path),
                "product_images_sync": product_images_sync,
                "counts": {
                    status: sum(item["status"] == status for item in results)
                    for status in (
                        "ready",
                        "existing",
                        "data_incomplete",
                        "ai_failed",
                        "invalid",
                        "failed",
                        "concurrency_exhausted",
                    )
                },
                "results": results,
            }
            sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
            failed_count = summary["counts"]["failed"] + summary["counts"]["ai_failed"]
            if failed_count:
                failed_messages = "；".join(
                    f"本品 {item['self_spu']} / 竞品 {item['competitor_spu']}："
                    f"{item.get('message') or '未知错误'}"
                    for item in results
                    if item["status"] in {"failed", "ai_failed"}
                )
                raise RuntimeError(f"有 {failed_count} 个商品对处理失败：{failed_messages}")
            concurrency_count = summary["counts"]["concurrency_exhausted"]
            if concurrency_count:
                LOGGER.error(
                    "有 %s 个商品对在数仓并发定向重试后仍然失败",
                    concurrency_count,
                )
                raise SystemExit(CONCURRENCY_EXHAUSTED_EXIT_CODE)
        except BaseException as error:
            status_writer.fail(error)
            raise
        else:
            status_writer.complete(summary["counts"])
