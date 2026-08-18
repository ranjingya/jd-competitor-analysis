"""把原始工作簿行整理为稳定的标准化事实契约。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .input_files import (
    parse_period_directory,
    period_fields,
    prepare_workbooks,
    validate_workbook_period,
)
from .sources import clean_identifier, discover_sources, read_rows, validate_rows_period


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PeriodRequest:
    """定义单周期分析输入。

    功能说明：隔离命令行参数与内部标准化、估算流程。
    参数 input_dir：当前周期的原始 ZIP/XLSX 目录。
    参数 granularity：分析粒度。
    参数 self_spu：本品 SPU。
    参数 competitor_spu：竞品 SPU。
    参数 competitor_prefix：竞品字段前缀。
    参数 title：报告标题。
    返回值：不可变的单周期请求对象。
    """

    input_dir: Path
    granularity: str
    self_spu: str
    competitor_spu: str
    competitor_prefix: str
    title: str


def _public_source(source: dict[str, Any]) -> dict[str, Any]:
    """生成可写入 JSON 的源文件信息。"""

    return {
        "role": source["role"],
        "label": source["label"],
        "file_name": source.get("file_name"),
        "sheet_name": source.get("sheet_name"),
        "required_level": source["required_level"],
        "status": source["status"],
        "warnings": list(source.get("warnings", [])),
    }


def normalize_period(request: PeriodRequest) -> dict[str, Any]:
    """生成单周期标准化事实。

    功能说明：发现六类输入文件，读取原始行，唯一匹配本品与核心对比行，并生成 `normalized_data`。
    参数 request：包含输入目录、周期、粒度和商品标识的单周期请求。
    返回值：符合标准化事实契约的字典。
    """

    period_input = parse_period_directory(request.input_dir, request.granularity)
    period_meta = period_fields(request.granularity, period_input.path.name)
    LOGGER.info("开始标准化周期：%s / %s", period_meta["period"], request.granularity)
    with prepare_workbooks(request.input_dir) as workbooks:
        for workbook in workbooks:
            validate_workbook_period(
                workbook,
                period_meta["period_start"],
                period_meta["period_end"],
            )
        sources = discover_sources(workbooks, request.competitor_prefix)
        rows_by_role = {role: read_rows(source) for role, source in sources.items()}
        for role, rows in rows_by_role.items():
            validate_rows_period(
                role,
                rows,
                request.granularity,
                period_meta["period_start"],
                period_meta["period_end"],
            )

    self_matches = [
        row for row in rows_by_role["self_real"] if clean_identifier(row.get("SPU")) == request.self_spu
    ]
    if len(self_matches) != 1:
        raise RuntimeError(f"本品 SPU 无法唯一匹配：{request.self_spu}，匹配行数={len(self_matches)}")
    if len(rows_by_role["core"]) != 1:
        raise RuntimeError(f"竞品核心数据对比必须唯一，当前行数={len(rows_by_role['core'])}")

    source_files = [_public_source(source) for source in sources.values()]
    warnings = []
    for source in sources.values():
        if source["status"] == "missing":
            warnings.append(f"缺少{source['label']}")
        elif source["status"] == "conflict":
            warnings.append(f"{source['label']}存在多个候选")
    generated_at = datetime.now().isoformat(timespec="seconds")
    normalized = {
        "schema_version": "1.0",
        "meta": {
            **period_meta,
            "period_file": period_input.path.name,
            "granularity": request.granularity,
            "self_spu": request.self_spu,
            "competitor_spu": request.competitor_spu,
            "competitor_prefix": request.competitor_prefix,
            "title": request.title,
            "generated_at": generated_at,
        },
        "source_files": source_files,
        "core_raw": rows_by_role["core"][0],
        "self_real": self_matches[0],
        "traffic_rows": rows_by_role["traffic"],
        "keyword_rows": rows_by_role["keywords"],
        "customer_profile_rows": rows_by_role["customer_profile"],
        "promotion_rows": rows_by_role["promotion"],
        "warnings": warnings,
    }
    LOGGER.info("周期标准化完成：%s", normalized["meta"]["period_key"])
    return normalized
