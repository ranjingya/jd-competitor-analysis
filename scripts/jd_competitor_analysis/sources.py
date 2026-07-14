"""发现并读取京东竞品分析的原始 Excel 数据。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


LOGGER = logging.getLogger(__name__)

ROLE_RULES = {
    "self_real": {
        "label": "本品真实 SPU 数据",
        "hints": ("spu真实数据", "商品明细"),
        "required": ("SPU", "访客数", "成交金额"),
        "level": "core",
    },
    "core": {
        "label": "竞品核心数据对比",
        "hints": ("竞品数据对比",),
        "required": ("本品访客数",),
        "level": "core",
    },
    "traffic": {
        "label": "流量来源对比",
        "hints": ("流量来源对比",),
        "required": ("一级渠道", "本品访客数"),
        "level": "core",
    },
    "keywords": {
        "label": "引流关键词对比",
        "hints": ("引流关键词对比",),
        "required": ("关键词", "SPUID", "访客数", "成交金额"),
        "level": "complete",
    },
    "customer_profile": {
        "label": "成交客户画像对比",
        "hints": ("成交客户对比",),
        "required": ("画像类型", "本品成交客户数占比"),
        "level": "complete",
    },
    "promotion": {
        "label": "推广数据对比",
        "hints": ("推广数据对比",),
        "required": (),
        "level": "enhancement",
    },
}

GRANULARITY_DIRS = {"day": "天", "week": "周", "month": "月"}


def clean_text(value: Any) -> str:
    """把单元格值转换为去除首尾空白的文本。"""

    return "" if value is None else str(value).strip()


def clean_identifier(value: Any) -> str:
    """把 Excel 中的数字标识统一为无小数文本。"""

    text = clean_text(value)
    return text[:-2] if text.endswith(".0") else text


def extract_dates(text: str) -> list[str]:
    """从文件名或周期文本提取 ISO 日期。"""

    return re.findall(r"\d{4}-\d{2}-\d{2}", text)


def period_matches(path: Path, period_file: str) -> bool:
    """判断文件名日期是否与目标周期完全一致。"""

    target_dates = extract_dates(period_file)
    file_dates = extract_dates(path.stem)
    return bool(target_dates) and file_dates[: len(target_dates)] == target_dates


def period_fields(granularity: str, period_text: str) -> dict[str, str]:
    """生成统一周期字段。

    功能说明：从周期文本生成展示周期、起止日期和唯一键。
    参数 granularity：分析粒度，取值为 day、week 或 month。
    参数 period_text：包含一个或两个 ISO 日期的周期文本。
    返回值：包含 period、period_start、period_end 和 period_key 的字典。
    """

    dates = extract_dates(period_text)
    if not dates:
        raise ValueError(f"周期未包含有效日期：{period_text}")
    period_start = dates[0]
    period_end = dates[-1]
    period = period_start if period_start == period_end else f"{period_start}~{period_end}"
    return {
        "period": period,
        "period_start": period_start,
        "period_end": period_end,
        "period_key": f"{granularity}:{period_start}_{period_end}",
    }


def discover_periods(input_dir: Path) -> list[tuple[str, str]]:
    """发现粒度目录中的全部分析周期。

    功能说明：以竞品核心数据对比文件为周期锚点，提取并排序每个独立起止日期。
    参数 input_dir：某一粒度的原始 Excel 目录。
    返回值：按开始日期和结束日期升序排列的周期元组列表。
    """

    periods: set[tuple[str, str]] = set()
    for path in input_dir.glob("*.xlsx"):
        if path.name.startswith("~$") or "竞品数据对比" not in path.stem:
            continue
        dates = extract_dates(path.stem)
        if not dates:
            LOGGER.warning("核心数据文件未识别到周期：%s", path.name)
            continue
        periods.add((dates[0], dates[-1]))
    result = sorted(periods)
    LOGGER.info("已发现周期：%s，共 %s 个", input_dir, len(result))
    return result


def period_in_window(period_start: str, period_end: str, start_date: str | None, end_date: str | None) -> bool:
    """判断周期是否落入调用方指定的分析窗口。"""

    if start_date and period_end < start_date:
        return False
    if end_date and period_start > end_date:
        return False
    return True


def validate_date_window(start_date: str | None, end_date: str | None) -> None:
    """校验批处理日期窗口。

    功能说明：校验可选起止日期的格式与前后顺序。
    参数 start_date：最早周期日期，可为空。
    参数 end_date：最晚周期日期，可为空。
    返回值：无；格式或顺序无效时抛出 ValueError。
    """

    for field_name, value in (("start_date", start_date), ("end_date", end_date)):
        if not value:
            continue
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError(f"{field_name} 必须使用 YYYY-MM-DD 格式：{value}") from error
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date 不能晚于 end_date")


def workbook_headers(path: Path) -> list[tuple[str, list[str]]]:
    """读取工作簿每个工作表的首行表头。"""

    workbook = load_workbook(path, read_only=False, data_only=True)
    result = []
    for sheet in workbook.worksheets:
        headers = [clean_text(sheet.cell(1, column).value) for column in range(1, sheet.max_column + 1)]
        result.append((sheet.title, headers))
    workbook.close()
    return result


def select_sheet(path: Path, required_headers: tuple[str, ...]) -> str:
    """按表头选择源工作表。

    功能说明：扫描所有工作表并选择满足角色字段要求的工作表。
    参数 path：Excel 文件路径。
    参数 required_headers：当前数据角色的基础必需表头。
    返回值：唯一匹配的工作表名称。
    """

    candidates = []
    headers_by_sheet = workbook_headers(path)
    for sheet_name, headers in headers_by_sheet:
        if all(header in set(headers) for header in required_headers):
            candidates.append(sheet_name)
    if not candidates and not required_headers:
        candidates = [item[0] for item in headers_by_sheet]
    if len(candidates) != 1:
        raise RuntimeError(f"工作表无法唯一匹配：{path.name}，候选={candidates}")
    return candidates[0]


def discover_sources(input_dir: Path, period_file: str, competitor_prefix: str) -> dict[str, dict[str, Any]]:
    """发现并确认六类真实源文件。

    功能说明：按周期、文件角色关键词和表头定位输入文件与工作表。
    参数 input_dir：当前粒度的原始 Excel 目录。
    参数 period_file：目标周期文件名片段。
    参数 competitor_prefix：目标竞品字段前缀。
    返回值：按数据角色组织的文件、工作表和完整性信息。
    """

    files = [path for path in input_dir.glob("*.xlsx") if not path.name.startswith("~$")]
    sources: dict[str, dict[str, Any]] = {}
    for role, rule in ROLE_RULES.items():
        period_files = [path for path in files if period_matches(path, period_file)]
        hinted_files = [
            path for path in period_files if any(hint.lower() in path.stem.lower() for hint in rule["hints"])
        ]
        required_headers = tuple(rule["required"])
        if role in {"core", "traffic"}:
            required_headers += (f"{competitor_prefix}访客数",)
        scan_pool = hinted_files or (period_files if required_headers else [])
        candidates = []
        for path in scan_pool:
            try:
                sheet_name = select_sheet(path, required_headers)
            except RuntimeError:
                continue
            candidates.append((path, sheet_name))
        if len(candidates) != 1:
            if rule["level"] == "core":
                raise RuntimeError(f"{rule['label']}无法唯一匹配，候选={[path.name for path, _ in candidates]}")
            LOGGER.warning("%s无法唯一匹配，按缺失处理", rule["label"])
            sources[role] = {
                "role": role,
                "label": rule["label"],
                "required_level": rule["level"],
                "status": "missing",
            }
            continue
        path, sheet_name = candidates[0]
        sources[role] = {
            "role": role,
            "label": rule["label"],
            "required_level": rule["level"],
            "status": "ready",
            "path": path,
            "file_name": path.name,
            "sheet_name": sheet_name,
        }
        LOGGER.info("已定位%s：%s / %s", rule["label"], path.name, sheet_name)
    return sources


def read_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    """读取已确认工作表的所有数据行。"""

    if source.get("status") != "ready":
        return []
    workbook = load_workbook(source["path"], read_only=False, data_only=True)
    sheet = workbook[source["sheet_name"]]
    headers = [clean_text(sheet.cell(1, column).value) for column in range(1, sheet.max_column + 1)]
    rows = []
    for row_index in range(2, sheet.max_row + 1):
        values = [sheet.cell(row_index, column).value for column in range(1, sheet.max_column + 1)]
        row = dict(zip(headers, values))
        row["_row_index"] = row_index
        rows.append(row)
    workbook.close()
    LOGGER.info("已读取%s：%s 行", source["label"], len(rows))
    return rows
