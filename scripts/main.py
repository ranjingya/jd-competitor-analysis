"""京东竞品分析 Skill 的唯一命令行入口。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from jd_competitor_analysis.pipeline import run_analysis
from jd_competitor_analysis.recommendations import apply_recommendations


def _add_analysis_arguments(parser: argparse.ArgumentParser) -> None:
    """注册分析子命令参数。"""

    parser.add_argument("--batch", action="store_true", help="扫描日、周、月目录并批量生成全部周期。")
    parser.add_argument("--input-root", help="批量模式的原始数据根目录，目录下包含天、周、月。")
    parser.add_argument("--input-dir", help="单周期模式的原始 Excel 目录。")
    parser.add_argument("--normalized-input", help="单周期重算使用的 normalized_data.json，提供后不读取 Excel。")
    parser.add_argument("--period-file", help="单周期模式的文件名周期片段，例如 YYYY-MM-DD_YYYY-MM-DD。")
    parser.add_argument("--period", help="单周期模式的页面展示周期，例如 YYYY-MM-DD~YYYY-MM-DD。")
    parser.add_argument("--granularity", choices=["day", "week", "month"], help="单周期模式的分析粒度。")
    parser.add_argument("--self-spu", help="本品 SPU。")
    parser.add_argument("--competitor-spu", help="竞品 SPU。")
    parser.add_argument("--competitor-prefix", default="竞品1", help="导出表中的目标竞品字段前缀。")
    parser.add_argument("--title", help="网页标题，默认使用“竞品准真实值看板”。")
    parser.add_argument("--start-date", help="批量模式的最早周期日期，格式为 YYYY-MM-DD。")
    parser.add_argument("--end-date", help="批量模式的最晚周期日期，格式为 YYYY-MM-DD。")
    parser.add_argument("--log-level", default="INFO", help="日志级别。")


def parse_args() -> argparse.Namespace:
    """解析统一入口的子命令和参数。

    功能说明：提供 `analyze` 与 `apply-ai` 两个外部操作，并为每个操作注册独立参数。
    返回值：包含子命令、处理函数和业务参数的命名空间。
    """

    parser = argparse.ArgumentParser(description="读取京东竞品数据，生成分析结果或写入 AI 建议。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="生成单周期或多周期竞品分析。")
    _add_analysis_arguments(analyze_parser)
    analyze_parser.set_defaults(handler=run_analysis)

    apply_parser = subparsers.add_parser("apply-ai", help="把 Skill 生成的 AI 建议写入分析结果。")
    apply_parser.add_argument("--recommendations", type=Path, required=True, help="AI 建议输入 JSON 路径。")
    apply_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    apply_parser.set_defaults(handler=lambda args: apply_recommendations(args.recommendations))
    return parser.parse_args()


def main() -> None:
    """执行京东竞品分析命令。

    功能说明：解析外部命令，初始化标准日志，并调用对应的内部业务流程。
    返回值：无；分析结果由对应流程固定写入 `scripts/output/`。
    """

    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger(__name__).info("开始执行命令：%s", args.command)
    args.handler(args)
    logging.getLogger(__name__).info("命令执行完成：%s", args.command)


if __name__ == "__main__":
    main()
