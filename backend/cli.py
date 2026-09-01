"""京东竞品分析后端的数据处理命令行入口。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from time import perf_counter

from app.jobs.daily_analysis import run_warehouse_daily_analysis
from app.jobs.period_analysis import run_period_analysis
from app.jobs.product_images import run_product_image_sync
from app.logging_config import configure_backend_logging
from jd_competitor_analysis.lark_mapping import run_lark_mapping_check
from jd_competitor_analysis.warehouse import run_warehouse_probe
from jd_competitor_analysis.warehouse_daily import run_warehouse_daily_check


def parse_args() -> argparse.Namespace:
    """解析统一入口的子命令和参数。

    功能说明：提供数仓连接探测、飞书映射检查、日数据来源检查、主图同步和正式日分析，
    并为每个操作注册独立参数。
    返回值：包含子命令、处理函数和业务参数的命名空间。
    """

    parser = argparse.ArgumentParser(description="读取数仓与飞书数据并生成京东竞品分析报告。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    warehouse_parser = subparsers.add_parser("warehouse-probe", help="验证数仓连接并读取少量样例数据。")
    warehouse_parser.add_argument("--env-file", type=Path, help="环境变量文件，默认读取项目根目录的 .env。")
    warehouse_parser.add_argument("--table", help="测试读取的表名，默认使用 DB_TEST_TABLE。")
    warehouse_parser.add_argument("--limit", type=int, help="返回样例行数，默认使用 DB_TEST_LIMIT。")
    warehouse_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    warehouse_parser.set_defaults(handler=run_warehouse_probe)

    lark_parser = subparsers.add_parser("lark-mapping-check", help="只读检查指定 SPU 的飞书 SKU 映射。")
    lark_parser.add_argument("--env-file", type=Path, help="环境变量文件，默认读取项目根目录的 .env。")
    lark_parser.add_argument("--spu-id", required=True, help="需要查询的本品 SPU ID。")
    lark_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    lark_parser.set_defaults(handler=run_lark_mapping_check)

    daily_check_parser = subparsers.add_parser("warehouse-daily-check", help="检查指定商品对的正式日数据来源。")
    daily_check_parser.add_argument("--env-file", type=Path, help="环境变量文件，默认读取项目根目录的 .env。")
    daily_check_parser.add_argument("--date", required=True, help="业务日期，格式为 YYYY-MM-DD。")
    daily_check_parser.add_argument("--self-spu", required=True, help="本品 SPU ID。")
    daily_check_parser.add_argument("--competitor-spu", required=True, help="竞品 SPU ID。")
    daily_check_parser.add_argument(
        "--sku-id",
        action="append",
        default=[],
        help="本品 SPU 下的 SKU ID，可重复提供；未提供时自动读取飞书映射。",
    )
    daily_check_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    daily_check_parser.set_defaults(handler=run_warehouse_daily_check)

    daily_run_parser = subparsers.add_parser("warehouse-daily-run", help="执行日数据分析并写入 Backend 数据库。")
    daily_run_parser.add_argument("--env-file", type=Path, help="环境变量文件，默认读取项目根目录的 .env。")
    date_group = daily_run_parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument("--date", help="业务日期，格式为 YYYY-MM-DD。")
    date_group.add_argument("--yesterday", action="store_true", help="使用服务器本地日期的昨天。")
    daily_run_parser.add_argument("--self-spu", help="手动指定本品 SPU；需要和 --competitor-spu 一起使用。")
    daily_run_parser.add_argument("--competitor-spu", help="手动指定竞品 SPU；需要和 --self-spu 一起使用。")
    daily_run_parser.add_argument("--title", help="可选看板标题。")
    daily_run_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    daily_run_parser.set_defaults(handler=run_warehouse_daily_analysis)

    weekly_parser = subparsers.add_parser(
        "weekly-report-run",
        help="聚合已完成日报并生成自然周报告。",
    )
    weekly_period_group = weekly_parser.add_mutually_exclusive_group(required=True)
    weekly_period_group.add_argument("--start-date", help="自然周周一，格式为 YYYY-MM-DD。")
    weekly_period_group.add_argument(
        "--previous-week",
        action="store_true",
        help="使用北京时间的上一个完整自然周。",
    )
    weekly_parser.add_argument("--self-spu", help="可选本品 SPU；需与 --competitor-spu 同时提供。")
    weekly_parser.add_argument("--competitor-spu", help="可选竞品 SPU；需与 --self-spu 同时提供。")
    weekly_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    weekly_parser.set_defaults(handler=run_period_analysis, granularity="week")

    monthly_parser = subparsers.add_parser(
        "monthly-report-run",
        help="聚合已完成日报并生成自然月报告。",
    )
    monthly_period_group = monthly_parser.add_mutually_exclusive_group(required=True)
    monthly_period_group.add_argument("--month", help="自然月，格式为 YYYY-MM。")
    monthly_period_group.add_argument(
        "--previous-month",
        action="store_true",
        help="使用北京时间的上一个完整自然月。",
    )
    monthly_parser.add_argument("--self-spu", help="可选本品 SPU；需与 --competitor-spu 同时提供。")
    monthly_parser.add_argument("--competitor-spu", help="可选竞品 SPU；需与 --self-spu 同时提供。")
    monthly_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    monthly_parser.set_defaults(handler=run_period_analysis, granularity="month")

    image_sync_parser = subparsers.add_parser(
        "sync-product-images",
        help="把运行数据目录中的商品主图配置同步到已有报告。",
    )
    image_sync_parser.add_argument("--log-level", default="INFO", help="日志级别。")
    image_sync_parser.set_defaults(handler=run_product_image_sync)

    return parser.parse_args()


def main() -> None:
    """执行京东竞品分析命令。

    功能说明：解析外部命令，初始化标准日志，并调用对应的内部业务流程。
    返回值：无；分析结果由对应流程写入 Backend 数据库。
    """

    started_at = perf_counter()
    args = parse_args()
    configure_backend_logging(getattr(logging, args.log_level.upper(), logging.INFO))
    logging.getLogger(__name__).info("开始执行命令：%s", args.command)
    args.handler(args)
    logging.getLogger(__name__).info(
        "命令执行完成：%s，耗时=%.3fs",
        args.command,
        perf_counter() - started_at,
    )


if __name__ == "__main__":
    main()
