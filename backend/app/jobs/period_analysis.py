"""编排周报和月报的日报聚合、DeepSeek 分析与持久化。"""

from __future__ import annotations

import json
import logging
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Any

from jd_competitor_analysis.period_aggregation import (
    aggregate_period_report,
    build_period_ai_payload,
)

from ..config import get_settings
from ..database import Database
from ..deepseek_analysis import DeepSeekAnalysisConfig, DeepSeekAnalyzer
from ..job_lock import acquire_job_lock
from ..logging_config import BEIJING_TIMEZONE
from ..repositories.report_repository import ReportRepository
from ..repositories.task_repository import TaskRepository
from .analysis import start_ai_analysis
from .daily_analysis import ALREADY_RUNNING_EXIT_CODE, AIAnalyzer, _processing_error_message


LOGGER = logging.getLogger(__name__)


def previous_week(today: date | None = None) -> tuple[str, str]:
    """计算上一个自然周的周一和周日。

    功能说明：以北京时间当天为基准，返回完整上一个自然周。
    参数 today：可选基准日期；为空时使用北京时间当天。
    返回值：开始日期和结束日期组成的二元组。
    """

    current = today or datetime.now(BEIJING_TIMEZONE).date()
    current_monday = current - timedelta(days=current.weekday())
    start = current_monday - timedelta(days=7)
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def week_from_start(start_date: str) -> tuple[str, str]:
    """从周一生成自然周日期范围。"""

    start = date.fromisoformat(start_date)
    if start.weekday() != 0:
        raise ValueError("周报开始日期必须是周一")
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def previous_month(today: date | None = None) -> tuple[str, str]:
    """计算上一个自然月的首日和末日。"""

    current = today or datetime.now(BEIJING_TIMEZONE).date()
    current_month_start = current.replace(day=1)
    end = current_month_start - timedelta(days=1)
    return end.replace(day=1).isoformat(), end.isoformat()


def month_range(month: str) -> tuple[str, str]:
    """把 YYYY-MM 转换为自然月日期范围。"""

    try:
        start = date.fromisoformat(f"{month}-01")
    except ValueError as error:
        raise ValueError("月份格式必须为 YYYY-MM") from error
    end = start.replace(day=monthrange(start.year, start.month)[1])
    return start.isoformat(), end.isoformat()


def _selected_period(args: Any) -> tuple[str, str, str]:
    """根据周期命令参数生成粒度和日期范围。"""

    if args.granularity == "week":
        start_date, end_date = (
            previous_week() if args.previous_week else week_from_start(args.start_date)
        )
    elif args.granularity == "month":
        start_date, end_date = (
            previous_month() if args.previous_month else month_range(args.month)
        )
    else:
        raise ValueError(f"不支持的周期粒度：{args.granularity}")
    return args.granularity, start_date, end_date


def _run_period_pair(
    daily_rows: list[dict[str, Any]],
    granularity: str,
    start_date: str,
    end_date: str,
    report_repository: ReportRepository,
    task_repository: TaskRepository,
    ai_analyzer: AIAnalyzer,
) -> dict[str, Any]:
    """生成并完成一个商品对的周期报告。

    功能说明：聚合已完成日报，按来源日报版本执行幂等判断，然后调用 DeepSeek 并合并报告。
    参数 daily_rows：同一商品对的已完成日报记录。
    参数 granularity：week 或 month。
    参数 start_date：周期开始日期。
    参数 end_date：周期结束日期。
    参数 report_repository：报告仓库。
    参数 task_repository：AI 执行记录仓库。
    参数 ai_analyzer：DeepSeek 分析器。
    返回值：当前商品对的周期报告处理摘要。
    """

    self_spu = str(daily_rows[0]["self_spu"])
    competitor_spu = str(daily_rows[0]["competitor_spu"])
    source_report_ids = [str(row["report_id"]) for row in daily_rows]
    existing = report_repository.find_ready_period_report(
        granularity, start_date, end_date, self_spu, competitor_spu
    )
    if existing is not None and existing["source_report_ids"] == source_report_ids:
        return {
            "self_spu": self_spu,
            "competitor_spu": competitor_spu,
            "status": "existing",
            "report_id": existing["report_id"],
            "available_days": len(daily_rows),
        }
    report = aggregate_period_report(daily_rows, granularity, start_date, end_date)
    report_id = report_repository.upsert(None, report, status="pending_ai")
    payload = build_period_ai_payload(report)
    start_result = start_ai_analysis(
        task_repository,
        report_id,
        payload,
        ai_analyzer.model,
        ai_analyzer.analysis_version,
        ai_analyzer.prompt_hash,
    )
    if not start_result.should_execute:
        return {
            "self_spu": self_spu,
            "competitor_spu": competitor_spu,
            "status": "existing",
            "report_id": report_id,
            "analysis_id": start_result.analysis_id,
            "available_days": len(daily_rows),
        }
    report_repository.activate_pending(report_id, None, report)
    try:
        ai_result = ai_analyzer.analyze(
            payload,
            {
                "analysis_id": start_result.analysis_id,
                "report_id": report_id,
                "granularity": granularity,
                "start_date": start_date,
                "end_date": end_date,
                "self_spu": self_spu,
                "competitor_spu": competitor_spu,
            },
        )
        task_repository.complete(start_result.analysis_id, ai_result)
    except Exception as error:
        message, _ = _processing_error_message(error)
        task_repository.fail(start_result.analysis_id, message)
        return {
            "self_spu": self_spu,
            "competitor_spu": competitor_spu,
            "status": "ai_failed",
            "report_id": report_id,
            "analysis_id": start_result.analysis_id,
            "available_days": len(daily_rows),
            "message": message,
        }
    return {
        "self_spu": self_spu,
        "competitor_spu": competitor_spu,
        "status": "ready",
        "report_id": report_id,
        "analysis_id": start_result.analysis_id,
        "available_days": len(daily_rows),
    }


def run_period_analysis(args: Any) -> None:
    """执行周报或月报聚合与 AI 分析。

    功能说明：从统一数据库读取周期内已完成日报，按商品对顺序聚合并生成一份周期报告；
    缺失日报会记录到周期元数据，但不会阻止其他可用日报生成报告。
    参数 args：包含粒度、周期选择、可选商品对过滤和日志参数的命令行参数。
    返回值：无；摘要写入标准输出，任一商品对失败时以异常结束。
    """

    started_at = perf_counter()
    granularity, start_date, end_date = _selected_period(args)
    settings = get_settings()
    with acquire_job_lock(settings.analysis_lock_path) as acquired:
        if not acquired:
            LOGGER.warning("周期报告任务未启动：已有分析任务正在运行")
            raise SystemExit(ALREADY_RUNNING_EXIT_CODE)
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY 尚未配置")
        database = Database(settings.database_path)
        database.initialize()
        report_repository = ReportRepository(database)
        task_repository = TaskRepository(database)
        ai_analyzer = DeepSeekAnalyzer(
            DeepSeekAnalysisConfig(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                timeout_seconds=settings.deepseek_timeout_seconds,
                max_attempts=settings.deepseek_max_attempts,
                usage_log_dir=settings.deepseek_usage_log_dir,
            )
        )
        daily_rows = report_repository.list_ready_day_reports(
            start_date,
            end_date,
            getattr(args, "self_spu", None),
            getattr(args, "competitor_spu", None),
        )
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in daily_rows:
            grouped[(row["self_spu"], row["competitor_spu"])].append(row)
        LOGGER.info(
            "%s任务开始：period=%s..%s，pairs=%s，daily_reports=%s",
            "周报" if granularity == "week" else "月报",
            start_date,
            end_date,
            len(grouped),
            len(daily_rows),
        )
        if not grouped:
            LOGGER.warning(
                "%s周期没有可聚合的已完成日报：period=%s..%s",
                "周报" if granularity == "week" else "月报",
                start_date,
                end_date,
            )
        results = []
        for index, pair_rows in enumerate(grouped.values(), start=1):
            pair_started_at = perf_counter()
            try:
                result = _run_period_pair(
                    pair_rows,
                    granularity,
                    start_date,
                    end_date,
                    report_repository,
                    task_repository,
                    ai_analyzer,
                )
            except Exception as error:
                message, _ = _processing_error_message(error)
                result = {
                    "self_spu": pair_rows[0]["self_spu"],
                    "competitor_spu": pair_rows[0]["competitor_spu"],
                    "status": "failed",
                    "report_id": None,
                    "available_days": len(pair_rows),
                    "message": message,
                }
                LOGGER.error(
                    "周期报告处理失败：self=%s，competitor=%s，原因=%s",
                    result["self_spu"],
                    result["competitor_spu"],
                    message,
                )
                LOGGER.debug("周期报告处理失败堆栈", exc_info=True)
            results.append(result)
            LOGGER.info(
                "[%s/%s] 周期报告完成：self=%s，competitor=%s，status=%s，days=%s，耗时=%.1fs",
                index,
                len(grouped),
                result["self_spu"],
                result["competitor_spu"],
                result["status"],
                result["available_days"],
                perf_counter() - pair_started_at,
            )
        counts = {
            status: sum(result["status"] == status for result in results)
            for status in ("ready", "existing", "ai_failed", "failed")
        }
        summary = {
            "granularity": granularity,
            "start_date": start_date,
            "end_date": end_date,
            "counts": counts,
        }
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        failed_count = counts["ai_failed"] + counts["failed"]
        if failed_count:
            messages = "；".join(
                f"本品 {item['self_spu']} / 竞品 {item['competitor_spu']}：{item.get('message')}"
                for item in results
                if item["status"] in {"ai_failed", "failed"}
            )
            raise RuntimeError(f"有 {failed_count} 个周期报告生成失败：{messages}")
        LOGGER.info(
            "%s任务完成：generated=%s，existing=%s，耗时=%.1fs",
            "周报" if granularity == "week" else "月报",
            counts["ready"],
            counts["existing"],
            perf_counter() - started_at,
        )
