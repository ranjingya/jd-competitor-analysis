"""定义后端内部数据结构。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AIAnalysisResult(BaseModel):
    """DeepSeek 生成的结构化分析结果。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
