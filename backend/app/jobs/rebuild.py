"""从数据库快照重建基础报告，保留已有 AI 内容。"""

import logging
import sqlite3
from pathlib import Path
from uuid import uuid4

from jd_competitor_analysis.period_aggregation import aggregate_period_report
from jd_competitor_analysis.time_utils import beijing_now_text
from jd_competitor_analysis.warehouse_analysis import analyze_daily_dataset

from ..config import get_settings
from ..database import Database
from ..job_lock import acquire_job_lock
from ..repositories.dataset_repository import DatasetRepository
from ..repositories.report_repository import ReportRepository


LOGGER = logging.getLogger(__name__)
AI_COLUMNS = {
    "advantage_summary", "weakness_summary", "advantage_detail_json",
    "weakness_detail_json", "ai_findings_json", "ai_recommendations_json",
}


def rebuild_reports(database_path: Path) -> dict:
    """备份数据库并原子更新已有基础报告。

    功能说明：从一致性快照重算日报，再聚合已有周月报；保留 AI 字段、状态和报告 ID。
    无源数据日报及依赖它的周期报告跳过，计算失败或原库发生变化时不写回。
    参数 database_path：已有数据库文件路径；调用方必须持有分析进程锁。
    返回值：备份路径、各粒度更新数量和跳过的报告 ID。
    """
    database_path = Path(database_path).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    backup_dir = database_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"rebuild-{uuid4().hex}.db"
    with sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True) as source:
        with sqlite3.connect(backup_path) as target:
            source.backup(target)
    backup_path.chmod(0o644)
    LOGGER.info("基础报告重建开始，备份：%s", backup_path)
    snapshot = Database(backup_path)
    reports = ReportRepository(snapshot)
    datasets = DatasetRepository(snapshot)
    with snapshot.connection() as con:
        original = [dict(r) for r in con.execute("SELECT * FROM reports ORDER BY report_id")]
        rebuilt = {}
        daily = []
        skipped = []
        counts = {"day": 0, "week": 0, "month": 0}
        ordered = sorted(original, key=lambda r: (r["granularity"] != "day", r["start_date"]))
        for row in ordered:
            rid = row["report_id"]
            old = reports.get(rid)
            if row["granularity"] == "day":
                if not row["dataset_id"]:
                    skipped.append(rid)
                    LOGGER.warning("跳过报告：%s，缺少原始日数据", rid)
                    continue
                payload = datasets.get(row["dataset_id"])["payload"]
                images = {str(old["meta"][key]["id"]): old["meta"][key]
                          for key in ("self_product", "competitor_product")
                          if old["meta"].get(key, {}).get("id")}
                report = analyze_daily_dataset(payload, title=old["meta"].get("title"), product_images=images)
            else:
                candidates = [d for d in daily if d["self_spu"] == row["self_spu"]
                              and d["competitor_spu"] == row["competitor_spu"]
                              and row["start_date"] <= d["report_date"] <= row["end_date"]]
                expected = {r["report_id"] for r in original if r["granularity"] == "day"
                            and r["status"] == "ready" and r["self_spu"] == row["self_spu"]
                            and r["competitor_spu"] == row["competitor_spu"]
                            and row["start_date"] <= r["start_date"] <= row["end_date"]}
                source_ids = set(old["meta"].get("source_report_ids") or [])
                available = {d["report_id"] for d in candidates}
                if not candidates or expected != available or not source_ids.issubset(available):
                    skipped.append(rid)
                    LOGGER.warning("跳过报告：%s，周期源日报不足或未完成重建", rid)
                    continue
                report = aggregate_period_report(candidates, row["granularity"], row["start_date"], row["end_date"])
            for key in ("self_name", "competitor_name", "self_product", "competitor_product", "title"):
                report["meta"][key] = old["meta"].get(key)
            content = reports._report_content(con, row["dataset_id"], report)
            # AI 列逐字保留，避免重新序列化改变旧分析内容。
            for key in AI_COLUMNS:
                content[key] = row[key]
            rebuilt[rid] = content
            counts[row["granularity"]] += 1
            if row["granularity"] == "day" and row["status"] == "ready":
                daily.append({**content, "report_id": rid, "report_date": row["start_date"],
                              "self_spu": row["self_spu"], "competitor_spu": row["competitor_spu"],
                              "report": report})
            LOGGER.info("基础报告已计算：%s，%s～%s，%s / %s", row["granularity"],
                        row["start_date"], row["end_date"], row["self_spu"], row["competitor_spu"])
    with Database(database_path).connection() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            current = [dict(r) for r in con.execute("SELECT * FROM reports ORDER BY report_id")]
            if current != original:
                raise RuntimeError("计算期间报告发生变化，取消写入，请停止其他写入后重试")
            for row in original:
                if row["report_id"] in rebuilt:
                    reports._update_report(con, row["report_id"], row["dataset_id"], row["status"],
                                           rebuilt[row["report_id"]], beijing_now_text())
            con.commit()
        except Exception:
            con.rollback()
            raise
    result = {"backup": str(backup_path), "updated": counts, "skipped": skipped}
    LOGGER.info("基础报告重建完成：日报=%s，周报=%s，月报=%s，跳过=%s；AI 内容保留",
                counts["day"], counts["week"], counts["month"], len(skipped))
    return result


def run_rebuild(args) -> None:
    """执行基础报告重建命令。

    参数 args：命令行参数，日志级别由统一入口处理。
    返回值：无；备份位置及处理结果输出到日志。
    """
    settings = get_settings()
    with acquire_job_lock(settings.analysis_lock_path) as acquired:
        if not acquired:
            raise RuntimeError("已有分析任务运行，本次未重建")
        rebuild_reports(settings.database_path)
