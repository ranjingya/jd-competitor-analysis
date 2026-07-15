"""编排单周期、批量和标准化事实重算流程。"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from . import OUTPUT_ROOT
from .contracts import read_json, validate_contract, write_json
from .estimation import PHistory, analyze_core
from .input_files import (
    GRANULARITY_DIRS,
    discover_periods,
    period_fields,
    period_in_window,
    validate_date_window,
)
from .normalization import PeriodRequest, normalize_period
from .output_paths import period_directory_name
from .report import build_analysis_result


LOGGER = logging.getLogger(__name__)
DEFAULT_TITLE = "竞品准真实值看板"


def analyze_normalized(normalized: dict[str, Any], history: PHistory | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """从标准化事实生成分析结果。

    功能说明：执行核心估算、分析域和报告组装，使算法调整后可以不读取 Excel 直接重算。
    参数 normalized：单周期标准化事实数据。
    参数 history：同商品、同粒度、此前周期的有效 P 样本。
    返回值：最终分析结果与当前周期新增的有效 P 样本。
    """

    period_key = normalized.get("meta", {}).get("period_key")
    LOGGER.info("开始分析标准化事实：%s", period_key)
    core = analyze_core(normalized, history)
    result = build_analysis_result(normalized, core)
    result["meta"]["generated_at"] = datetime.now().isoformat(timespec="seconds")
    validate_contract(result)
    LOGGER.info("标准化事实分析完成：%s", period_key)
    return result, core["p_samples"]


def analyze_period(request: PeriodRequest, history: PHistory | None = None) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """读取原始工作簿并完成单周期分析。

    功能说明：先读取 ZIP/XLSX 并生成稳定的标准化事实，再调用独立分析阶段生成最终结果。
    参数 request：单周期输入请求。
    参数 history：同商品、同粒度、此前周期的有效 P 样本。
    返回值：最终分析结果、标准化事实和当前周期新增的有效 P 样本。
    """

    normalized = normalize_period(request)
    result, samples = analyze_normalized(normalized, history)
    return result, normalized, samples


def _period_request(args: argparse.Namespace) -> PeriodRequest:
    """从命令行参数生成内部单周期请求。"""

    return PeriodRequest(
        input_dir=Path(args.input_dir).resolve(),
        granularity=args.granularity,
        self_spu=args.self_spu,
        competitor_spu=args.competitor_spu,
        competitor_prefix=args.competitor_prefix,
        title=args.title or DEFAULT_TITLE,
    )


def _extend_history(history: PHistory, samples: list[dict[str, Any]]) -> None:
    """把当前周期有效 P 样本加入同粒度历史。"""

    for sample in samples:
        history.setdefault(sample["metric_id"], []).append(sample)


def _new_report_index(title: str, self_spu: str, competitor_spu: str) -> dict[str, Any]:
    """创建固定输出目录使用的报告索引。"""

    return {
        "schema_version": "1.0",
        "updated_at": None,
        "meta": {
            "title": title,
            "self_spu": self_spu,
            "competitor_spu": competitor_spu,
        },
        "reports": {granularity: [] for granularity in GRANULARITY_DIRS},
    }


def _report_entry(result: dict[str, Any]) -> dict[str, Any]:
    """从单周期分析结果生成轻量索引条目。"""

    meta = result["meta"]
    period_file = period_directory_name(
        meta["granularity"],
        meta["period_start"],
        meta["period_end"],
    )
    return {
        "period": meta["period"],
        "period_start": meta["period_start"],
        "period_end": meta["period_end"],
        "period_key": meta["period_key"],
        "generated_at": meta["generated_at"],
        "confidence": meta["confidence"],
        "path": f"/reports/{meta['granularity']}/{period_file}/analysis_result.json",
    }


def _write_period_result(result: dict[str, Any], normalized: dict[str, Any]) -> None:
    """把单周期结果写入固定输出目录并更新索引。

    功能说明：按粒度和周期写入两份 JSON，将当前周期插入或替换到 `report-index.json`。
    参数 result：最终分析结果。
    参数 normalized：当前周期标准化事实。
    返回值：无；固定写入 `scripts/output/`。
    """

    meta = result["meta"]
    period_file = period_directory_name(
        meta["granularity"],
        meta["period_start"],
        meta["period_end"],
    )
    period_dir = OUTPUT_ROOT / meta["granularity"] / period_file
    index_path = OUTPUT_ROOT / "report-index.json"
    report_index = (
        read_json(index_path)
        if index_path.is_file()
        else _new_report_index(meta["title"], meta["self_spu"], meta["competitor_spu"])
    )
    index_meta = report_index.get("meta", {})
    if (
        index_meta.get("self_spu") not in {None, meta["self_spu"]}
        or index_meta.get("competitor_spu") not in {None, meta["competitor_spu"]}
    ):
        raise ValueError("scripts/output 中的报告索引属于其他商品对，请先整理固定输出目录")
    write_json(period_dir / "normalized_data.json", normalized)
    write_json(period_dir / "analysis_result.json", result)
    report_index["meta"] = {
        "title": meta["title"],
        "self_spu": meta["self_spu"],
        "competitor_spu": meta["competitor_spu"],
    }
    reports = report_index.setdefault("reports", {granularity: [] for granularity in GRANULARITY_DIRS})
    for granularity in GRANULARITY_DIRS:
        reports.setdefault(granularity, [])
    entries = [item for item in reports[meta["granularity"]] if item.get("period_key") != meta["period_key"]]
    entries.append(_report_entry(result))
    entries.sort(key=lambda item: (item["period_start"], item["period_end"]))
    reports[meta["granularity"]] = entries
    report_index["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(index_path, report_index)


def run_single(args: argparse.Namespace) -> None:
    """执行单周期分析。

    功能说明：读取单周期 ZIP/XLSX 或已有标准化事实，生成分析结果并更新固定输出目录和报告索引。
    参数 args：包含输入、商品和周期的命令行参数。
    返回值：无；成功时写入 `scripts/output/`。
    """

    if args.normalized_input:
        normalized = read_json(Path(args.normalized_input))
        if args.title:
            normalized.setdefault("meta", {})["title"] = args.title
        result, _ = analyze_normalized(normalized)
    else:
        required = {
            "input_dir": args.input_dir,
            "granularity": args.granularity,
            "self_spu": args.self_spu,
            "competitor_spu": args.competitor_spu,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"单周期模式缺少参数：{', '.join(missing)}")
        result, normalized, _ = analyze_period(_period_request(args))
    _write_period_result(result, normalized)
    LOGGER.info("单周期分析完成：%s", result["meta"]["period_key"])


def run_batch(args: argparse.Namespace) -> None:
    """执行日、周、月多周期批量分析。

    功能说明：分别扫描三个粒度目录，按时间顺序分析每个周期，独立维护同粒度历史 P 并生成报告索引。
    参数 args：包含输入根目录、商品信息和可选日期窗口的命令行参数。
    返回值：无；成功时写入 `scripts/output/` 下的周期结果和报告索引。
    """

    if not args.input_root:
        raise ValueError("批量模式必须提供 --input-root")
    if not args.self_spu or not args.competitor_spu:
        raise ValueError("批量模式必须提供 --self-spu 和 --competitor-spu")
    validate_date_window(args.start_date, args.end_date)
    input_root = Path(args.input_root).resolve()
    if not input_root.is_dir():
        raise ValueError(f"批量输入根目录不存在：{input_root}")
    if not any((input_root / directory_name).is_dir() for directory_name in GRANULARITY_DIRS.values()):
        raise ValueError(f"输入根目录中未发现 day、week 或 month：{input_root}")
    report_index = _new_report_index(args.title or DEFAULT_TITLE, args.self_spu, args.competitor_spu)

    for granularity, directory_name in GRANULARITY_DIRS.items():
        input_dir = input_root / directory_name
        history: PHistory = {}
        if not input_dir.is_dir():
            LOGGER.warning("粒度目录不存在，跳过：%s", input_dir)
            continue
        for period_input in discover_periods(input_dir, granularity):
            period_start = period_input.period_start
            period_end = period_input.period_end
            if not period_in_window(period_start, period_end, args.start_date, args.end_date):
                continue
            period_file = period_input.path.name
            period_meta = period_fields(granularity, period_file)
            request = PeriodRequest(
                input_dir=period_input.path,
                granularity=granularity,
                self_spu=args.self_spu,
                competitor_spu=args.competitor_spu,
                competitor_prefix=args.competitor_prefix,
                title=args.title or DEFAULT_TITLE,
            )
            output_period_file = period_directory_name(granularity, period_start, period_end)
            period_dir = OUTPUT_ROOT / granularity / output_period_file
            LOGGER.info("开始处理周期：%s", period_meta["period_key"])
            result, normalized, samples = analyze_period(request, history)
            write_json(period_dir / "normalized_data.json", normalized)
            write_json(period_dir / "analysis_result.json", result)
            _extend_history(history, samples)
            report_index["reports"][granularity].append(_report_entry(result))
            LOGGER.info("周期处理完成：%s", period_meta["period_key"])

    report_index["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(OUTPUT_ROOT / "report-index.json", report_index)
    counts = {key: len(value) for key, value in report_index["reports"].items()}
    LOGGER.info("批量分析完成：%s", counts)


def run_analysis(args: argparse.Namespace) -> None:
    """按命令行模式启动分析。

    功能说明：根据 `--batch` 在单周期和多粒度批处理之间分流。
    参数 args：分析子命令解析后的参数。
    返回值：无。
    """

    if args.batch:
        run_batch(args)
    else:
        run_single(args)
