"""读取已有日报事实并强制重新生成 AI 内容。"""

import logging
from datetime import date
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from ..config import get_settings
from ..database import Database
from ..deepseek_analysis import DeepSeekAnalyzer, DeepSeekAnalysisConfig
from ..job_lock import acquire_job_lock
from ..repositories.report_repository import ReportRepository
from ..repositories.task_repository import TaskRepository

LOGGER = logging.getLogger(__name__)


def reanalyze_reports(database_path, report_date, analyzer, self_spu=None, competitor_spu=None):
    """强制重跑指定日期已有日报的 AI，逐商品对保存结果。

    参数 database_path：已有数据库路径；调用方须持有分析进程锁。
    参数 report_date：业务日期，格式 YYYY-MM-DD。
    参数 analyzer：AI 分析器，负责当前提示词、请求重试及用量记录。
    参数 self_spu：可选本品 SPU；单独提供时选择该本品全部已有竞品报告。
    参数 competitor_spu：可选竞品 SPU；提供时必须同时指定 self_spu。
    返回值：成功和失败数量；单项失败保留基础数据并继续其他项。
    """
    if date.fromisoformat(report_date).isoformat() != report_date:
        raise ValueError("日期格式必须为 YYYY-MM-DD")
    if competitor_spu and not self_spu:
        raise ValueError("提供 --competitor-spu 时必须同时提供 --self-spu")
    if not Path(database_path).is_file():
        raise FileNotFoundError(database_path)
    database = Database(database_path)
    reports = ReportRepository(database)
    tasks = TaskRepository(database)
    query = "SELECT report_id, self_spu, competitor_spu FROM reports WHERE granularity = 'day' AND start_date = ? AND end_date = ? AND status IN ('ready', 'ai_failed', 'pending_ai')"
    params = [report_date, report_date]
    if self_spu:
        query += " AND self_spu = ?"
        params.append(self_spu)
    if competitor_spu:
        query += " AND competitor_spu = ?"
        params.append(competitor_spu)
    with database.connection() as connection:
        rows = connection.execute(query + " ORDER BY self_spu, competitor_spu", params).fetchall()
    if not rows:
        raise ValueError("指定日期和商品范围没有可分析的已有日报")
    LOGGER.info("AI 重分析开始：date=%s，reports=%s", report_date, len(rows))
    counts = {"ready": 0, "failed": 0}
    for index, row in enumerate(rows, 1):
        started = perf_counter()
        analysis_id = None
        try:
            report = reports.get(row["report_id"])
            payload = {
                "period": {"granularity": "day", "start_date": report_date,
                           "end_date": report_date, "period_days": 1,
                           "available_days": 1, "missing_days": []},
                "pair": {key: report["meta"].get(key) for key in
                         ("self_spu", "competitor_spu", "self_name", "competitor_name")},
                "self_spu_data": {"spu_id": row["self_spu"], "metrics": {
                    item["metric_id"]: item.get("self_value") for item in report["comparison"]}},
                "tables": {"core_metrics": report["comparison"],
                           "traffic_sources": report["traffic_sources"],
                           "traffic_keywords": report["keywords"],
                           "customer_profiles": report["customer_profile"],
                           "promotion": report["promotion"]},
                "risks": report["risks"],
            }
            # 每次人工重分析创建独立执行版本，保留历史任务，不复用已完成 AI。
            task = tasks.start(row["report_id"], f"reanalyze:{uuid4().hex}", payload,
                               analyzer.model, analyzer.analysis_version, analyzer.prompt_hash)
            analysis_id = task.analysis_id
            reports.mark_ai_pending(row["report_id"])
            result = analyzer.analyze(payload, {
                "analysis_id": analysis_id, "report_id": row["report_id"],
                "granularity": "day", "start_date": report_date, "end_date": report_date,
                "self_spu": row["self_spu"], "competitor_spu": row["competitor_spu"],
            })
            tasks.complete(analysis_id, result)
            counts["ready"] += 1
            LOGGER.info("[%s/%s] AI 重分析成功：self=%s，competitor=%s，耗时=%.1fs",
                        index, len(rows), row["self_spu"], row["competitor_spu"], perf_counter() - started)
        except Exception as error:
            if analysis_id:
                tasks.fail(analysis_id, str(error))
            counts["failed"] += 1
            LOGGER.error("[%s/%s] AI 重分析失败：self=%s，competitor=%s，原因=%s",
                         index, len(rows), row["self_spu"], row["competitor_spu"], error)
    LOGGER.info("AI 重分析完成：成功=%s，失败=%s", counts["ready"], counts["failed"])
    return counts


def run_reanalyze(args):
    """执行命令并复用正式分析锁和 DeepSeek 配置。

    参数 args：含 date、可选 self_spu、competitor_spu 的命令行参数。
    返回值：无；有 AI 失败时退出码为 14，已有分析运行时为 12。
    """
    settings = get_settings()
    with acquire_job_lock(settings.analysis_lock_path) as acquired:
        if not acquired:
            raise SystemExit(12)
        analyzer = DeepSeekAnalyzer(DeepSeekAnalysisConfig(**{
            name: getattr(settings, f"deepseek_{name}") for name in (
                "api_key", "base_url", "model",
                "timeout_seconds", "max_attempts", "pricing_path", "usage_log_dir")
        }))
        counts = reanalyze_reports(settings.database_path, args.date, analyzer,
                                   args.self_spu, args.competitor_spu)
        if counts["failed"]:
            raise SystemExit(14)
