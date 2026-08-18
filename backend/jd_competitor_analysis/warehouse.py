"""数仓连接配置与只读探测。"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import NullPool


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class WarehouseConfig:
    """保存数仓连接与探测参数，敏感字段不参与对象展示。"""

    driver: str
    host: str | None
    port: int | None
    database: str | None
    username: str | None
    password: str | None = field(repr=False)
    url: str | None = field(default=None, repr=False)
    connect_timeout_seconds: int = 10
    test_table: str | None = None
    test_limit: int = 5


def _optional_text(name: str) -> str | None:
    """读取可为空的环境变量并清理首尾空白。"""

    value = os.getenv(name, "").strip()
    return value or None


def _positive_integer(name: str, default: int, maximum: int | None = None) -> int:
    """读取有上限约束的正整数环境变量。"""

    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} 必须是正整数：{raw_value}") from error
    if value <= 0 or (maximum is not None and value > maximum):
        suffix = f" 且不大于 {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} 必须大于 0{suffix}：{value}")
    return value


def load_warehouse_config(env_file: Path | None = None) -> WarehouseConfig:
    """加载数仓连接配置。

    功能说明：从指定 `.env` 或项目根目录 `.env` 加载环境变量，支持完整 SQLAlchemy URL，
    也支持按方言、主机、端口、库名、账号和密码分别配置。
    参数 env_file：环境变量文件路径；为空时使用项目根目录 `.env`。
    返回值：完成基础格式校验的数仓配置对象。
    """

    resolved_env_file = (env_file or PROJECT_ROOT / ".env").expanduser().resolve()
    if resolved_env_file.exists():
        LOGGER.info("加载数仓环境变量：%s", resolved_env_file)
        load_dotenv(resolved_env_file, override=False)
    else:
        LOGGER.warning("环境变量文件不存在，将仅使用进程环境变量：%s", resolved_env_file)

    url = _optional_text("DB_URL")
    driver = _optional_text("DB_DRIVER") or "mysql+pymysql"
    host = _optional_text("DB_HOST")
    database = _optional_text("DB_NAME")
    username = _optional_text("DB_USER")
    password = os.getenv("DB_PASSWORD") or None
    port_value = _optional_text("DB_PORT")
    try:
        port = int(port_value) if port_value else None
    except ValueError as error:
        raise ValueError(f"DB_PORT 必须是整数：{port_value}") from error

    if not url:
        missing = [
            name
            for name, value in (
                ("DB_HOST", host),
                ("DB_NAME", database),
                ("DB_USER", username),
                ("DB_PASSWORD", password),
            )
            if value is None
        ]
        if missing:
            raise ValueError(f"数仓连接配置不完整，缺少：{', '.join(missing)}")

    return WarehouseConfig(
        driver=driver,
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        url=url,
        connect_timeout_seconds=_positive_integer("DB_CONNECT_TIMEOUT", 10, 120),
        test_table=_optional_text("DB_TEST_TABLE"),
        test_limit=_positive_integer("DB_TEST_LIMIT", 5, 100),
    )


def create_warehouse_engine(config: WarehouseConfig) -> Engine:
    """创建数仓连接引擎。

    功能说明：根据完整 URL 或分项参数创建 SQLAlchemy 引擎，不建立持久连接池，便于命令行探测后立即释放。
    参数 config：已校验的数仓连接配置。
    返回值：尚未执行 SQL 的 SQLAlchemy Engine。
    """

    connection_url: str | URL
    if config.url:
        connection_url = config.url
    else:
        connection_url = URL.create(
            drivername=config.driver,
            username=config.username,
            password=config.password,
            host=config.host,
            port=config.port,
            database=config.database,
        )

    connect_args: dict[str, Any] = {}
    if make_url(connection_url).get_backend_name() != "sqlite":
        connect_args["connect_timeout"] = config.connect_timeout_seconds
    return create_engine(
        connection_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        poolclass=NullPool,
    )


def _quote_table_name(engine: Engine, table_name: str) -> str:
    """校验并引用数据库、Schema 和表名。"""

    parts = table_name.split(".")
    if not parts or any(not IDENTIFIER_PATTERN.fullmatch(part) for part in parts):
        raise ValueError(f"测试表名包含非法字符：{table_name}")
    quote = engine.dialect.identifier_preparer.quote
    return ".".join(quote(part) for part in parts)


def probe_warehouse(config: WarehouseConfig, table_name: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """验证数仓连接并读取样例数据。

    功能说明：先执行无业务副作用的 `SELECT 1`，再按可选表名执行带行数限制的只读查询，返回列名和样例行。
    参数 config：数仓连接与默认探测参数。
    参数 table_name：需要抽样的表名；为空时使用配置中的测试表，为空则只测试连接。
    参数 limit：样例行数；为空时使用配置默认值，最大允许 100 行。
    返回值：包含连接状态、数据库方言、目标表、列名和样例行的结构化结果。
    """

    selected_table = table_name or config.test_table
    selected_limit = limit if limit is not None else config.test_limit
    if selected_limit <= 0 or selected_limit > 100:
        raise ValueError(f"样例行数必须在 1 到 100 之间：{selected_limit}")

    engine = create_warehouse_engine(config)
    quoted_table = _quote_table_name(engine, selected_table) if selected_table else None
    LOGGER.info("开始验证数仓连接，方言=%s", engine.dialect.name)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 AS connection_ok")).one()
            LOGGER.info("数仓连接验证成功")
            result: dict[str, Any] = {
                "connection_ok": True,
                "dialect": engine.dialect.name,
                "table": selected_table,
                "columns": [],
                "rows": [],
            }
            if selected_table:
                LOGGER.info("开始读取数仓样例：表=%s，行数=%s", selected_table, selected_limit)
                query_result = connection.execute(text(f"SELECT * FROM {quoted_table} LIMIT {selected_limit}"))
                result["columns"] = list(query_result.keys())
                result["rows"] = [dict(row) for row in query_result.mappings().all()]
                LOGGER.info("数仓样例读取完成：表=%s，实际行数=%s", selected_table, len(result["rows"]))
            return result
    except Exception:
        LOGGER.exception("数仓连接或样例读取失败")
        raise
    finally:
        engine.dispose()


def run_warehouse_probe(args: Any) -> None:
    """执行命令行数仓探测。

    功能说明：加载 `.env` 配置，执行连接与样例读取，并向标准输出写入便于人工核对的 JSON。
    参数 args：命令行参数，包含可选 env_file、table 和 limit。
    返回值：无；成功结果写入标准输出，异常由统一命令入口返回。
    """

    config = load_warehouse_config(args.env_file)
    result = probe_warehouse(config, table_name=args.table, limit=args.limit)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
