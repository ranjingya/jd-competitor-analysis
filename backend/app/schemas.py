"""定义后端内部数据结构。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AISummaryItem(BaseModel):
    """DeepSeek 生成的一类结论摘要。"""

    model_config = ConfigDict(extra="forbid")

    brief: str = Field(min_length=1, max_length=30)
    detail: list[str] = Field(min_length=1, max_length=6)


class AISummary(BaseModel):
    """DeepSeek 生成的优点与弱点摘要。"""

    model_config = ConfigDict(extra="forbid")

    advantage: AISummaryItem
    weakness: AISummaryItem


class AIAnalysisResult(BaseModel):
    """DeepSeek 生成的结构化分析结果。"""

    model_config = ConfigDict(extra="forbid")

    summary: AISummary
    findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
