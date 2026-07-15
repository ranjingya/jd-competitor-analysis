"""维护分析结果的固定输出路径规则。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import OUTPUT_ROOT


PERIOD_KEY_PATTERN = re.compile(
    r"^(day|week|month):(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$"
)


def _validate_date(value: str) -> None:
    """校验输出路径使用的 ISO 日期。"""

    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"输出周期日期无效：{value}") from error


def period_directory_name(granularity: str, period_start: str, period_end: str) -> str:
    """生成粒度对应的输出周期目录名。

    功能说明：日维度使用单日期目录，周和月使用起止日期范围目录。
    参数 granularity：分析粒度，取值为 day、week 或 month。
    参数 period_start：周期开始日期。
    参数 period_end：周期结束日期。
    返回值：当前周期在固定输出目录中的子目录名。
    """

    if granularity not in {"day", "week", "month"}:
        raise ValueError(f"输出粒度无效：{granularity}")
    _validate_date(period_start)
    _validate_date(period_end)
    if period_start > period_end:
        raise ValueError(f"输出周期起止日期顺序错误：{period_start}_{period_end}")
    if granularity == "day":
        if period_start != period_end:
            raise ValueError(f"日维度起止日期必须相同：{period_start}_{period_end}")
        return period_start
    return f"{period_start}_{period_end}"


def analysis_path_from_period_key(period_key: str) -> Path:
    """根据周期唯一键定位分析结果。

    功能说明：解析标准 `period_key`，按粒度目录规则返回固定分析结果路径。
    参数 period_key：格式为 `粒度:开始日期_结束日期` 的周期唯一键。
    返回值：`scripts/output/` 下对应的 `analysis_result.json` 路径。
    """

    matched = PERIOD_KEY_PATTERN.fullmatch(period_key)
    if matched is None:
        raise ValueError(f"period_key 无效：{period_key}")
    granularity, period_start, period_end = matched.groups()
    period_directory = period_directory_name(granularity, period_start, period_end)
    return OUTPUT_ROOT / granularity / period_directory / "analysis_result.json"
