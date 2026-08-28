"""提供项目统一的北京时间生成与转换能力。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


BEIJING_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")


def beijing_now() -> datetime:
    """返回当前北京时间。

    功能说明：生成带 `+08:00` 时区信息的当前时间，供运行状态和时间计算使用。
    返回值：带北京时间时区信息的 `datetime`。
    """

    return datetime.now(BEIJING_TIMEZONE)


def beijing_now_text() -> str:
    """返回秒精度的当前北京时间文本。

    功能说明：生成统一的 ISO 8601 时间文本，用于数据库、状态文件和 API 字段。
    返回值：形如 `2026-08-28T10:30:00+08:00` 的字符串。
    """

    return beijing_now().isoformat(timespec="seconds")


def normalize_beijing_time_text(value: str | None) -> str | None:
    """把已有时间文本规范化为北京时间。

    功能说明：将带时区的时间转换为 `+08:00`；无时区时间按既有北京时间解释。
    参数 value：待转换的 ISO 8601 时间文本；允许为空。
    返回值：秒精度、带 `+08:00` 的时间文本；空值保持为空。
    """

    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TIMEZONE)
    return parsed.astimezone(BEIJING_TIMEZONE).isoformat(timespec="seconds")
