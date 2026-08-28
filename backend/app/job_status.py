"""持久化日报批处理的实时运行状态。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from jd_competitor_analysis.time_utils import beijing_now, beijing_now_text


LOGGER = logging.getLogger(__name__)
STATUS_SCHEMA_VERSION = "1.0"
STALE_PROGRESS_SECONDS = 15 * 60


def read_daily_analysis_status(path: Path) -> dict[str, Any]:
    """读取日报运行状态。

    功能说明：读取共享数据目录中的状态快照；任务尚未运行时返回稳定的空闲结构。
    参数 path：日报状态 JSON 文件路径。
    返回值：当前运行状态或空闲状态对象。
    """

    if not path.exists():
        return {
            "schema_version": STATUS_SCHEMA_VERSION,
            "status": "idle",
            "stage": "idle",
            "process_alive": False,
            "progress_age_seconds": None,
            "stale": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        LOGGER.error("日报运行状态读取失败：path=%s，error=%s", path, error)
        return {
            "schema_version": STATUS_SCHEMA_VERSION,
            "status": "unknown",
            "stage": "status_unavailable",
            "error": str(error),
            "process_alive": False,
            "progress_age_seconds": None,
            "stale": True,
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": STATUS_SCHEMA_VERSION,
            "status": "unknown",
            "stage": "status_invalid",
            "error": "日报运行状态不是 JSON 对象",
            "process_alive": False,
            "progress_age_seconds": None,
            "stale": True,
        }
    status = str(payload.get("status") or "unknown")
    raw_pid = payload.get("pid")
    process_alive = False
    if status == "running" and isinstance(raw_pid, int) and raw_pid > 0:
        try:
            os.kill(raw_pid, 0)
            process_alive = True
        except ProcessLookupError:
            process_alive = False
        except PermissionError:
            process_alive = True
    progress_age_seconds: int | None = None
    raw_progress_at = payload.get("progress_at")
    if isinstance(raw_progress_at, str):
        try:
            progress_at = datetime.fromisoformat(raw_progress_at)
            if progress_at.tzinfo is not None:
                progress_age_seconds = max(
                    0,
                    int((beijing_now() - progress_at).total_seconds()),
                )
        except ValueError:
            progress_age_seconds = None
    result = dict(payload)
    result.update(
        {
            "process_alive": process_alive,
            "progress_age_seconds": progress_age_seconds,
            "stale": status == "running"
            and (
                not process_alive
                or progress_age_seconds is None
                or progress_age_seconds > STALE_PROGRESS_SECONDS
            ),
        }
    )
    return result


class DailyAnalysisStatusWriter:
    """原子写入单个日报批次的运行状态。"""

    def __init__(self, path: Path) -> None:
        """初始化状态写入器。

        功能说明：保存状态文件位置并为当前进程生成唯一运行 ID。
        参数 path：共享数据目录中的状态 JSON 文件路径。
        返回值：无。
        """

        self.path = path
        self.run_id = str(uuid.uuid4())
        self.payload: dict[str, Any] = {}

    def start(self, primary_date: str, dates: list[str]) -> None:
        """记录日报批次开始。

        功能说明：初始化运行身份、进程、日期范围、进度计数和开始时间。
        参数 primary_date：本次任务的主业务日期。
        参数 dates：本次检查的全部业务日期。
        返回值：无。
        """

        now = beijing_now_text()
        self.payload = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": "running",
            "stage": "starting",
            "pid": os.getpid(),
            "primary_date": primary_date,
            "dates": dates,
            "current_date": None,
            "self_spu": None,
            "competitor_spu": None,
            "completed_items": 0,
            "total_items": 0,
            "started_at": now,
            "progress_at": now,
            "completed_at": None,
            "error": None,
        }
        self._write()
        LOGGER.debug("日报运行状态已创建：run_id=%s，path=%s", self.run_id, self.path)

    def progress(
        self,
        stage: str,
        *,
        current_date: str | None = None,
        self_spu: str | None = None,
        competitor_spu: str | None = None,
        completed_items: int | None = None,
        total_items: int | None = None,
    ) -> None:
        """更新日报批次最近业务进度。

        功能说明：在日期、商品对或处理阶段推进时刷新状态文件，供宿主机和 API 判断任务位置。
        参数 stage：当前稳定阶段标识。
        参数 current_date：当前业务日期。
        参数 self_spu：当前本品 SPU。
        参数 competitor_spu：当前竞品 SPU。
        参数 completed_items：已经结束的日期商品对数量。
        参数 total_items：本批次日期商品对总数。
        返回值：无。
        """

        if not self.payload:
            raise RuntimeError("日报运行状态尚未开始")
        self.payload.update(
            {
                "status": "running",
                "stage": stage,
                "current_date": current_date,
                "self_spu": self_spu,
                "competitor_spu": competitor_spu,
                "progress_at": beijing_now_text(),
            }
        )
        if completed_items is not None:
            self.payload["completed_items"] = completed_items
        if total_items is not None:
            self.payload["total_items"] = total_items
        self._write()
        LOGGER.debug(
            "日报运行进度已更新：run_id=%s，stage=%s，completed=%s，total=%s",
            self.run_id,
            stage,
            self.payload["completed_items"],
            self.payload["total_items"],
        )

    def complete(self, counts: dict[str, int]) -> None:
        """记录日报批次成功完成。

        功能说明：保存最终计数并将状态更新为完成。
        参数 counts：按处理状态汇总的最终数量。
        返回值：无。
        """

        now = beijing_now_text()
        self.payload.update(
            {
                "status": "completed",
                "stage": "completed",
                "current_date": None,
                "self_spu": None,
                "competitor_spu": None,
                "progress_at": now,
                "completed_at": now,
                "counts": counts,
                "error": None,
            }
        )
        self._write()
        LOGGER.debug("日报运行状态已完成：run_id=%s", self.run_id)

    def fail(self, error: BaseException) -> None:
        """记录日报批次失败或中断。

        功能说明：保留最后业务阶段和进度，补充错误类型、摘要及结束时间。
        参数 error：导致批次退出的异常或中断信号。
        返回值：无。
        """

        now = beijing_now_text()
        last_stage = self.payload.get("stage")
        self.payload.update(
            {
                "status": "failed",
                "stage": "failed",
                "last_stage": last_stage,
                "progress_at": now,
                "completed_at": now,
                "error": {
                    "type": error.__class__.__name__,
                    "message": str(error)[:1000],
                },
            }
        )
        self._write()
        LOGGER.error(
            "日报运行状态已失败：run_id=%s，error=%s",
            self.run_id,
            self.payload["error"],
        )

    def _write(self) -> None:
        """通过同目录临时文件原子替换当前状态。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(self.payload, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
