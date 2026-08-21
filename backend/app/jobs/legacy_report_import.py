"""适配并导入历史 Excel 分析报告。"""

from __future__ import annotations

import copy
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from jd_competitor_analysis.contracts import read_json, validate_contract
from jd_competitor_analysis.report import relative_gap_pct

from ..config import get_settings
from ..database import Database
from ..repositories.report_repository import ReportRepository


LOGGER = logging.getLogger(__name__)
HIGHLIGHT_METRICS = {
    "traffic": ("访客", "relative"),
    "keywords": ("访客", "relative"),
    "customer_profile": ("成交客户占比", "percentage_point"),
}


def _number(value: Any) -> int | float | None:
    """读取可直接参与差值计算的 JSON 数值。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _gap_fields(
    self_value: Any,
    competitor_value: Any,
    gap_mode: str,
) -> dict[str, Any]:
    """根据已保存的本品和竞品值补充当前差距字段。"""

    selected_self = _number(self_value)
    selected_competitor = _number(competitor_value)
    comparable = selected_self is not None and selected_competitor is not None
    return {
        "gap_value": selected_self - selected_competitor if comparable else None,
        "gap_rate_pct": (
            relative_gap_pct(selected_self, selected_competitor)
            if comparable and gap_mode == "relative"
            else None
        ),
        "gap_mode": gap_mode,
    }


def adapt_legacy_report(source: dict[str, Any]) -> dict[str, Any]:
    """把历史最终报告适配为当前报告契约。

    功能说明：完整复制历史报告，仅补充当前契约需要的 AI 发现、数值差距和差距模式字段，
    不重新估算数仓指标，不修改旧报告已有的文本、明细和 AI 建议。
    参数 source：历史 `analysis_result.json` 反序列化后的报告对象。
    返回值：通过当前 JSON 契约校验的独立报告对象。
    """

    if not isinstance(source, dict):
        raise ValueError("历史报告必须是 JSON 对象")
    report = copy.deepcopy(source)
    meta = report.get("meta")
    if isinstance(meta, dict):
        meta.pop("confidence", None)
    if not isinstance(report.get("ai_findings"), list):
        report["ai_findings"] = []

    for item in report.get("comparison", []):
        if not isinstance(item, dict):
            continue
        gap_mode = (
            "percentage_point"
            if item.get("metric_id") == "conversion_rate"
            else "relative"
        )
        item.setdefault("gap_mode", gap_mode)
        item.setdefault(
            "gap_rate_pct",
            None
            if gap_mode == "percentage_point"
            else relative_gap_pct(
                _number(item.get("self_value")),
                _number(item.get("competitor_value")),
            ),
        )

    for item in report.get("core_metrics", []):
        if not isinstance(item, dict):
            continue
        gap_mode = (
            "percentage_point"
            if item.get("id") == "conversion_rate" or item.get("unit") == "%"
            else "relative"
        )
        for field, value in _gap_fields(
            item.get("self_value"),
            item.get("competitor_value"),
            gap_mode,
        ).items():
            item.setdefault(field, value)

    for tab in report.get("tabs", []):
        if not isinstance(tab, dict):
            continue
        metric_label, gap_mode = HIGHLIGHT_METRICS.get(
            str(tab.get("id") or ""),
            ("指标值", "relative"),
        )
        for item in tab.get("highlights", []):
            if not isinstance(item, dict):
                continue
            item.setdefault("metric_label", metric_label)
            for field, value in _gap_fields(
                item.get("self_value"),
                item.get("competitor_value"),
                gap_mode,
            ).items():
                item.setdefault(field, value)

    validate_contract(report)
    return report


def import_legacy_reports(
    input_root: Path,
    repository: ReportRepository,
) -> dict[str, Any]:
    """批量导入一个历史报告目录。

    功能说明：扫描 day、week、month 下的最终报告，逐份适配当前结构并以 ready 状态写入报告表；
    相同粒度、周期和商品对重复执行时更新同一份报告。
    参数 input_root：包含 day、week、month 目录的历史报告根目录。
    参数 repository：当前 Backend 报告仓库。
    返回值：包含导入数量、粒度统计和报告 ID 的摘要。
    """

    selected_root = input_root.expanduser().resolve()
    report_paths = sorted(
        path
        for granularity in ("day", "week", "month")
        for path in (selected_root / granularity).glob("*/analysis_result.json")
    )
    if not report_paths:
        raise FileNotFoundError(f"历史报告目录中没有 analysis_result.json：{selected_root}")

    started_at = perf_counter()
    counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    LOGGER.info("开始导入历史报告：root=%s，count=%d", selected_root, len(report_paths))
    for path in report_paths:
        item_started_at = perf_counter()
        report = adapt_legacy_report(read_json(path))
        meta = report["meta"]
        report_id = repository.upsert(None, report, status="ready")
        granularity = str(meta["granularity"])
        counts[granularity] += 1
        results.append(
            {
                "report_id": report_id,
                "granularity": granularity,
                "start_date": str(meta["period_start"]),
                "end_date": str(meta["period_end"]),
                "self_spu": str(meta["self_spu"]),
                "competitor_spu": str(meta["competitor_spu"]),
                "source_path": str(path),
            }
        )
        LOGGER.info(
            "历史报告导入完成：granularity=%s，start=%s，end=%s，report_id=%s，耗时=%.3fs",
            granularity,
            meta["period_start"],
            meta["period_end"],
            report_id,
            perf_counter() - item_started_at,
        )

    summary = {
        "input_root": str(selected_root),
        "count": len(results),
        "counts": {name: counts[name] for name in ("day", "week", "month")},
        "elapsed_seconds": round(perf_counter() - started_at, 3),
        "results": results,
    }
    LOGGER.info(
        "历史报告批量导入完成：count=%d，耗时=%.3fs",
        len(results),
        perf_counter() - started_at,
    )
    return summary


def run_legacy_report_import(args: Any) -> None:
    """执行历史报告导入命令。

    功能说明：初始化目标 Backend 数据库，导入指定目录中的历史最终报告并输出 JSON 摘要。
    参数 args：包含 input_root 和可选 database_path 的命令行参数。
    返回值：无；导入摘要写入标准输出。
    """

    settings = get_settings()
    database_path = (
        args.database_path.expanduser().resolve()
        if args.database_path is not None
        else settings.database_path
    )
    database = Database(database_path)
    database.initialize()
    summary = import_legacy_reports(args.input_root, ReportRepository(database))
    summary["database_path"] = str(database_path)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
