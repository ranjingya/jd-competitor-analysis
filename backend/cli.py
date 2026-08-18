"""京东竞品分析后端的数据处理命令行入口。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from jd_competitor_analysis.pipeline import run_analysis
from jd_competitor_analysis.recommendations import apply_recommendations
from jd_competitor_analysis.warehouse import run_warehouse_probe


def _add_analysis_arguments(parser: argparse.ArgumentParser) -> None:
    """注册分析子命令参数。"""

    parser.add_argument("--batch", action="store_true", help="扫描 day、week、month 目录并批量生成全部周期。")
    parser.add_argument("--input-root", help="批量模式的原始数据根目录，目录下包含 day、week、month。")
    parser.add_argument("--input-dir", help="单周期模式的原始 ZIP/XLSX 周期目录。")
    parser.add_argument("--normalized-input", help="单周期重算使用的 normalized_data.json，提供后不读取工作簿。")
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

    功能说明：提供分析、AI 建议写回和数仓连接探测操作，并为每个操作注册独立参数。
    返回值：包含子命令、处理函数和业务参数的命名空间。
    """

    parser = argparse.ArgumentParser(description="读取京东竞品数据，生成分析结果或执行数仓探测。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="生成单周期或多周期竞品分析。")
    _add_analysis_arguments(analyze_parser)
    analyze_parser.set_defaults(handler=run_analysis)

    apply_parser = subparsers.add_parser("apply-ai", help="兼容导入旧格式 AI 劣势建议。")
    apply_parser.add_argument("--recommendations", type=Path, required=True, help="AI 劣势建议输入 JSON 路径。")
    apply_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    apply_parser.set_defaults(handler=lambda args: apply_recommendations(args.recommendations))

    warehouse_parser = subparsers.add_parser("warehouse-probe", help="验证数仓连接并读取少量样例数据。")
    warehouse_parser.add_argument("--env-file", type=Path, help="环境变量文件，默认读取项目根目录的 .env。")
    warehouse_parser.add_argument("--table", help="测试读取的表名，默认使用 DB_TEST_TABLE。")
    warehouse_parser.add_argument("--limit", type=int, help="返回样例行数，默认使用 DB_TEST_LIMIT。")
    warehouse_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    warehouse_parser.set_defaults(handler=run_warehouse_probe)
    return parser.parse_args()


def main() -> None:
    """执行京东竞品分析命令。

    功能说明：解析外部命令，初始化标准日志，并调用对应的内部业务流程。
    返回值：无；分析结果由对应流程固定写入 `backend/output/`。
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
