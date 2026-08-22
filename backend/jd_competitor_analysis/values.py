"""提供数仓和报告处理共用的基础值清理函数。"""

from __future__ import annotations

from typing import Any


def clean_text(value: Any) -> str:
    """把任意来源值转换为去除首尾空白的文本。"""

    return "" if value is None else str(value).strip()


def clean_identifier(value: Any) -> str:
    """把可能以浮点形式展示的数字标识转换为文本。"""

    text = clean_text(value)
    return text[:-2] if text.endswith(".0") else text
