"""读取后端生成的看板报告。"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
GRANULARITIES = {"day", "week", "month"}
PERIOD_DIRECTORY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:_\d{4}-\d{2}-\d{2})?$")


class ReportRepository:
    """从持久化目录读取报告索引与单周期报告。"""

    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = reports_dir

    def read_index(self) -> dict[str, Any]:
        """读取并转换报告索引。

        功能说明：读取报告索引，为前端返回稳定的日、周、月数组，并把历史静态路径转换为 API 路径。
        返回值：可直接由前端消费的报告索引。
        """

        index_path = self.reports_dir / "report-index.json"
        if not index_path.is_file():
            LOGGER.warning("报告索引不存在，返回空索引：%s", index_path)
            return {
                "schema_version": "1.0",
                "updated_at": None,
                "meta": {},
                "reports": {granularity: [] for granularity in sorted(GRANULARITIES)},
            }
        index = json.loads(index_path.read_text(encoding="utf-8"))
        LOGGER.info("读取报告索引：%s", index_path)
        response = deepcopy(index)
        reports = response.setdefault("reports", {})
        for granularity in GRANULARITIES:
            entries = reports.setdefault(granularity, [])
            for entry in entries:
                period_directory = self._period_directory_from_entry(entry)
                entry["path"] = f"/api/reports/{granularity}/{period_directory}"
        return response

    def read_report(self, granularity: str, period_directory: str) -> dict[str, Any]:
        """读取单周期报告。

        功能说明：校验粒度和周期目录后读取对应 `analysis_result.json`，避免任意路径访问。
        参数 granularity：报告粒度，只允许 day、week 或 month。
        参数 period_directory：由日期或日期区间组成的周期目录名。
        返回值：单周期完整分析结果。
        """

        if granularity not in GRANULARITIES:
            raise ValueError(f"不支持的报告粒度：{granularity}")
        if not PERIOD_DIRECTORY_PATTERN.fullmatch(period_directory):
            raise ValueError(f"报告周期目录格式无效：{period_directory}")
        path = self.reports_dir / granularity / period_directory / "analysis_result.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        LOGGER.info("读取单周期报告：%s", path)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _period_directory_from_entry(entry: dict[str, Any]) -> str:
        """从索引条目解析周期目录。"""

        path = str(entry.get("path") or "")
        parts = [part for part in path.split("/") if part]
        if parts:
            candidate = parts[-2] if len(parts) >= 2 and parts[-1] == "analysis_result.json" else parts[-1]
            if PERIOD_DIRECTORY_PATTERN.fullmatch(candidate):
                return candidate
        period_key = str(entry.get("period_key") or "")
        candidate = period_key.split(":", 1)[-1]
        if PERIOD_DIRECTORY_PATTERN.fullmatch(candidate):
            return candidate
        raise ValueError(f"报告索引条目缺少有效周期目录：{entry}")
