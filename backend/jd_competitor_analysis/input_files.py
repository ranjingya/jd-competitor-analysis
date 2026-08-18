"""管理京东原始数据的周期目录、ZIP 和 XLSX 输入。"""

from __future__ import annotations

import logging
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator
from zipfile import BadZipFile, ZipFile


LOGGER = logging.getLogger(__name__)

GRANULARITY_DIRS = {"day": "day", "week": "week", "month": "month"}


@dataclass(frozen=True)
class PeriodInput:
    """定义一个已确认的周期输入目录。

    功能说明：保存批量模式发现的粒度周期、起止日期和原始文件目录。
    参数 path：当前周期的原始文件目录。
    参数 period_start：周期开始日期。
    参数 period_end：周期结束日期。
    返回值：不可变的周期输入对象。
    """

    path: Path
    period_start: str
    period_end: str


@dataclass(frozen=True)
class WorkbookInput:
    """定义一个可读取的工作簿输入。

    功能说明：统一表示直接提供的 XLSX 与从 ZIP 临时展开的 XLSX。
    参数 path：当前进程可读取的工作簿路径。
    参数 file_name：写入来源审计信息的原始文件标识。
    参数 date_name：用于校验报表周期的工作簿文件名。
    返回值：不可变的工作簿输入对象。
    """

    path: Path
    file_name: str
    date_name: str


def extract_dates(text: str) -> list[str]:
    """从文件名、目录名或周期文本中提取 ISO 日期。"""

    return re.findall(r"\d{4}-\d{2}-\d{2}", text)


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


def _validate_iso_date(value: str, field_name: str) -> None:
    """校验一个 ISO 日期文本。"""

    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{field_name} 必须使用 YYYY-MM-DD 格式：{value}") from error


def parse_period_directory(path: Path, granularity: str) -> PeriodInput:
    """解析并校验一个周期目录名。

    功能说明：按分析粒度校验周期目录格式、日期有效性和起止顺序。
    参数 path：当前周期原始文件目录。
    参数 granularity：当前目录对应的分析粒度。
    返回值：包含目录路径和起止日期的周期输入对象。
    """

    day_pattern = r"^\d{4}-\d{2}-\d{2}$"
    range_pattern = r"^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}$"
    expected_pattern = day_pattern if granularity == "day" else range_pattern
    if not re.fullmatch(expected_pattern, path.name):
        expected = "YYYY-MM-DD" if granularity == "day" else "YYYY-MM-DD_YYYY-MM-DD"
        raise ValueError(f"周期目录格式错误：{path}，{granularity} 应使用 {expected}")
    dates = extract_dates(path.name)
    period_start = dates[0]
    period_end = dates[-1]
    _validate_iso_date(period_start, "周期开始日期")
    _validate_iso_date(period_end, "周期结束日期")
    if period_start > period_end:
        raise ValueError(f"周期目录起止日期顺序错误：{path}")
    return PeriodInput(path=path, period_start=period_start, period_end=period_end)


def discover_periods(input_dir: Path, granularity: str) -> list[PeriodInput]:
    """发现一个粒度目录中的全部周期。

    功能说明：按输入约定扫描直接子目录，校验周期目录名并按起止日期排序。
    参数 input_dir：`day`、`week` 或 `month` 粒度目录。
    参数 granularity：当前目录对应的分析粒度。
    返回值：按开始日期和结束日期升序排列的周期输入列表。
    """

    flat_files = [
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".xlsx", ".zip"}
    ]
    if flat_files:
        raise ValueError(f"粒度目录必须按周期建立子目录，发现平铺文件：{flat_files[0]}")

    periods = [
        parse_period_directory(path, granularity)
        for path in input_dir.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    periods.sort(key=lambda item: (item.period_start, item.period_end))
    LOGGER.info("已发现周期：%s，共 %s 个", input_dir, len(periods))
    return periods


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
        if value:
            _validate_iso_date(value, field_name)
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date 不能晚于 end_date")


def validate_workbook_period(workbook: WorkbookInput, period_start: str, period_end: str) -> None:
    """校验工作簿文件名中的日期。

    功能说明：用工作簿自身文件名确认其日期属于当前周期；无日期文件名交由表内时间校验。
    参数 workbook：直接 XLSX 或 ZIP 内工作簿输入。
    参数 period_start：当前周期开始日期。
    参数 period_end：当前周期结束日期。
    返回值：无；文件名日期冲突时抛出 RuntimeError。
    """

    dates = extract_dates(workbook.date_name)
    if not dates:
        return
    if period_start == period_end:
        matched = all(value == period_start for value in dates)
    elif len(dates) == 1:
        matched = period_start <= dates[0] <= period_end
    else:
        matched = dates[0] == period_start and dates[-1] == period_end
    if not matched:
        raise RuntimeError(
            f"工作簿文件名周期与目录冲突：{workbook.file_name}，"
            f"目录周期={period_start}_{period_end}"
        )


def _extract_archive(source: Path, target_dir: Path, archive_index: int) -> list[WorkbookInput]:
    """把一个 ZIP 中的 XLSX 安全展开到临时目录。"""

    workbooks: list[WorkbookInput] = []
    try:
        with ZipFile(source) as archive:
            for member_index, member in enumerate(archive.infolist()):
                if member.is_dir() or Path(member.filename).suffix.lower() != ".xlsx":
                    continue
                inner_name = member.filename.replace("\\", "/")
                if Path(inner_name).name.startswith("~$"):
                    continue
                target = target_dir / f"{archive_index:03d}_{member_index:03d}_{Path(inner_name).name}"
                with archive.open(member) as input_stream, target.open("wb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream)
                workbooks.append(
                    WorkbookInput(
                        path=target,
                        file_name=f"{source.name}!{inner_name}",
                        date_name=inner_name,
                    )
                )
    except (BadZipFile, OSError) as error:
        raise RuntimeError(f"ZIP 无法读取：{source.name}") from error
    if not workbooks:
        LOGGER.warning("ZIP 中未发现 XLSX：%s", source.name)
    else:
        LOGGER.info("ZIP 展开完成：%s，共 %s 个 XLSX", source.name, len(workbooks))
    return workbooks


@contextmanager
def prepare_workbooks(input_dir: Path) -> Iterator[list[WorkbookInput]]:
    """准备一个周期目录中的全部工作簿。

    功能说明：直接引用 XLSX，并把 ZIP 内 XLSX 安全展开到生命周期受控的临时目录。
    参数 input_dir：包含当前周期原始 ZIP 和 XLSX 的目录。
    返回值：上下文生命周期内可读取的工作簿输入列表。
    """

    if not input_dir.is_dir():
        raise ValueError(f"周期输入目录不存在：{input_dir}")
    LOGGER.info("开始准备周期输入：%s", input_dir)
    with TemporaryDirectory(prefix="jd-competitor-input-") as temporary_directory:
        target_dir = Path(temporary_directory)
        workbooks: list[WorkbookInput] = []
        input_files = sorted(input_dir.iterdir(), key=lambda path: path.name.lower())
        for archive_index, source in enumerate(input_files):
            if not source.is_file() or source.name.startswith("~$"):
                continue
            suffix = source.suffix.lower()
            if suffix == ".xlsx":
                workbooks.append(
                    WorkbookInput(path=source, file_name=source.name, date_name=source.name)
                )
            elif suffix == ".zip":
                workbooks.extend(_extract_archive(source, target_dir, archive_index))
            else:
                LOGGER.warning("忽略非 ZIP/XLSX 输入：%s", source.name)
        if not workbooks:
            raise RuntimeError(f"周期目录中未发现可读取的 XLSX：{input_dir}")
        LOGGER.info("周期输入准备完成：%s，共 %s 个工作簿", input_dir, len(workbooks))
        yield workbooks
