"""编排单周期、批量和标准化事实重算流程。"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import empty_contract, read_json, validate_contract, write_json
from .estimation import PHistory, analyze_core
from .normalization import PeriodRequest, normalize_period
from .report import build_analysis_result
from .sources import (
    GRANULARITY_DIRS,
    discover_periods,
    period_fields,
    period_in_window,
    validate_date_window,
)


LOGGER = logging.getLogger(__name__)


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
    """读取 Excel 并完成单周期分析。

    功能说明：先生成稳定的标准化事实，再调用独立分析阶段生成最终结果。
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
        input_dir=Path(args.input_dir),
        period_file=args.period_file,
        period=args.period,
        granularity=args.granularity,
        self_spu=args.self_spu,
        competitor_spu=args.competitor_spu,
        competitor_prefix=args.competitor_prefix,
        title=args.title,
    )


def _extend_history(history: PHistory, samples: list[dict[str, Any]]) -> None:
    """把当前周期有效 P 样本加入同粒度历史。"""

    for sample in samples:
        history.setdefault(sample["metric_id"], []).append(sample)


def run_single(args: argparse.Namespace) -> None:
    """执行单周期分析。

    功能说明：读取单周期 Excel 或已有标准化事实，生成分析结果及可选标准化数据和空模板。
    参数 args：包含输入、商品、周期和输出路径的命令行参数。
    返回值：无；成功时写入调用方指定文件。
    """

    if not args.output_json:
        raise ValueError("单周期模式必须提供 --output-json")
    if args.normalized_input:
        normalized = read_json(Path(args.normalized_input))
        if args.title:
            normalized.setdefault("meta", {})["title"] = args.title
        result, _ = analyze_normalized(normalized)
    else:
        required = {
            "input_dir": args.input_dir,
            "period_file": args.period_file,
            "period": args.period,
            "granularity": args.granularity,
            "self_spu": args.self_spu,
            "competitor_spu": args.competitor_spu,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"单周期模式缺少参数：{', '.join(missing)}")
        result, normalized, _ = analyze_period(_period_request(args))
    write_json(Path(args.output_json), result)
    if args.output_normalized:
        write_json(Path(args.output_normalized), normalized)
    if args.empty_template_output:
        empty = empty_contract()
        validate_contract(empty, allow_empty=True)
        write_json(Path(args.empty_template_output), empty)
    LOGGER.info("单周期分析完成：%s", result["meta"]["period_key"])


def run_batch(args: argparse.Namespace) -> None:
    """执行日、周、月多周期批量分析。

    功能说明：分别扫描三个粒度目录，按时间顺序分析每个周期，独立维护同粒度历史 P 并生成报告索引。
    参数 args：包含输入根目录、输出根目录、商品信息和可选日期窗口的命令行参数。
    返回值：无；成功时写入周期结果和 `report-index.json`。
    """

    if not args.input_root or not args.output_root:
        raise ValueError("批量模式必须提供 --input-root 和 --output-root")
    if not args.self_spu or not args.competitor_spu:
        raise ValueError("批量模式必须提供 --self-spu 和 --competitor-spu")
    validate_date_window(args.start_date, args.end_date)
    input_root = Path(args.input_root).resolve()
    output_root = Path(args.output_root).resolve()
    report_index: dict[str, Any] = {
        "schema_version": "1.0",
        "updated_at": None,
        "meta": {
            "title": args.title,
            "self_spu": args.self_spu,
            "competitor_spu": args.competitor_spu,
        },
        "reports": {granularity: [] for granularity in GRANULARITY_DIRS},
    }

    for granularity, directory_name in GRANULARITY_DIRS.items():
        input_dir = input_root / directory_name
        history: PHistory = {}
        if not input_dir.is_dir():
            LOGGER.warning("粒度目录不存在，跳过：%s", input_dir)
            continue
        for period_start, period_end in discover_periods(input_dir):
            if not period_in_window(period_start, period_end, args.start_date, args.end_date):
                continue
            period_file = f"{period_start}_{period_end}"
            period_meta = period_fields(granularity, period_file)
            request = PeriodRequest(
                input_dir=input_dir,
                period_file=period_file,
                period=period_meta["period"],
                granularity=granularity,
                self_spu=args.self_spu,
                competitor_spu=args.competitor_spu,
                competitor_prefix=args.competitor_prefix,
                title=args.title,
            )
            period_dir = output_root / granularity / period_file
            LOGGER.info("开始处理周期：%s", period_meta["period_key"])
            result, normalized, samples = analyze_period(request, history)
            write_json(period_dir / "normalized_data.json", normalized)
            write_json(period_dir / "analysis_result.json", result)
            _extend_history(history, samples)
            report_index["reports"][granularity].append(
                {
                    **period_meta,
                    "generated_at": result["meta"]["generated_at"],
                    "confidence": result["meta"]["confidence"],
                    "path": f"/reports/{granularity}/{period_file}/analysis_result.json",
                }
            )
            LOGGER.info("周期处理完成：%s", period_meta["period_key"])

    report_index["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(output_root / "report-index.json", report_index)
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
