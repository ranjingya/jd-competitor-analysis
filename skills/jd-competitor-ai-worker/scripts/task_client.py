"""Mac Codex 使用的 AI 任务领取与回传客户端。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)
SKILL_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ClientConfig:
    """保存 AI 任务接口连接参数。"""

    api_url: str
    token: str
    worker_id: str
    timeout_seconds: int


def _load_env_file(path: Path) -> None:
    """加载简单 KEY=VALUE 格式环境变量文件。"""

    if not path.is_file():
        LOGGER.warning("本地环境变量文件不存在，将仅使用进程环境变量：%s", path)
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        normalized_value = value.strip().strip("\"'")
        os.environ.setdefault(name.strip(), normalized_value)


def load_config(env_file: Path | None) -> ClientConfig:
    """加载客户端配置。

    功能说明：读取 Skill 本地 `.env` 或指定文件，并校验后端地址、令牌、Worker 标识和超时。
    参数 env_file：可选环境变量文件；为空时读取 Skill 目录 `.env`。
    返回值：完成校验的 API 客户端配置。
    """

    _load_env_file((env_file or SKILL_ROOT / ".env").expanduser().resolve())
    api_url = os.getenv("ANALYSIS_API_URL", "").strip().rstrip("/")
    token = os.getenv("ANALYSIS_API_TOKEN", "").strip()
    worker_id = os.getenv("ANALYSIS_WORKER_ID", "").strip()
    missing = [
        name
        for name, value in (
            ("ANALYSIS_API_URL", api_url),
            ("ANALYSIS_API_TOKEN", token),
            ("ANALYSIS_WORKER_ID", worker_id),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"AI 任务客户端配置不完整，缺少：{', '.join(missing)}")
    try:
        timeout_seconds = int(os.getenv("ANALYSIS_API_TIMEOUT", "30"))
    except ValueError as error:
        raise ValueError("ANALYSIS_API_TIMEOUT 必须是正整数") from error
    if timeout_seconds <= 0:
        raise ValueError("ANALYSIS_API_TIMEOUT 必须大于 0")
    return ClientConfig(api_url, token, worker_id, timeout_seconds)


def request_json(
    config: ClientConfig,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    """发送带鉴权的 JSON 请求。

    功能说明：向后端发送 JSON 请求并解析响应，保留 204 无任务语义，异常时返回可排查的服务端信息。
    参数 config：已校验的客户端连接参数。
    参数 method：HTTP 方法。
    参数 path：以斜杠开头的 API 相对路径。
    参数 payload：可选请求 JSON 对象；GET 请求可为空。
    返回值：HTTP 状态码和可空 JSON 响应。
    """

    request = Request(
        url=f"{config.api_url}{path}",
        data=(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        ),
        method=method,
        headers={
            "Authorization": f"Bearer {config.token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read()
            if response.status == 204 or not body:
                return response.status, None
            return response.status, json.loads(body.decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"后端返回 HTTP {error.code}：{body}") from error
    except URLError as error:
        raise RuntimeError(f"无法连接分析后端：{error.reason}") from error


def _read_object(path: Path) -> dict[str, Any]:
    """读取并检查 JSON 对象。"""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return data


def list_tasks(config: ClientConfig, status: str | None, limit: int) -> None:
    """查看后端任务列表。

    功能说明：按生成时间倒序读取任务摘要，并以 JSON 输出任务 ID、生成时间、状态和商品对等信息。
    参数 config：客户端连接参数。
    参数 status：可选任务状态筛选条件。
    参数 limit：最多返回的任务数量。
    返回值：无；任务列表输出到标准输出。
    """

    query = {"limit": limit}
    if status:
        query["status"] = status
    _, response = request_json(config, "GET", f"/analysis-tasks?{urlencode(query)}")
    if not isinstance(response, dict):
        raise RuntimeError("后端任务列表响应格式无效")
    print(json.dumps(response, ensure_ascii=False, indent=2))
    LOGGER.info("任务列表读取完成：count=%s，status=%s", response.get("count"), status or "all")


def claim_task(config: ClientConfig, output_path: Path) -> None:
    """领取任务并写入临时文件。

    功能说明：向后端领取一条任务；没有任务时写入 task=null，便于定时任务正常结束。
    参数 config：客户端连接参数。
    参数 output_path：任务临时 JSON 保存路径。
    返回值：无。
    """

    status_code, task = request_json(
        config,
        "POST",
        "/analysis-tasks/claim",
        {"worker_id": config.worker_id},
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"task": task if status_code != 204 else None}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if task is None:
        LOGGER.info("当前没有待处理任务：output=%s", output_path)
        return
    LOGGER.info(
        "任务领取完成：analysis_id=%s，created_at=%s，report_date=%s，"
        "compare_number=%s，attempt_count=%s，lease_expires_at=%s，output=%s",
        task.get("analysis_id"),
        task.get("created_at"),
        task.get("report_date"),
        task.get("compare_number"),
        task.get("attempt_count"),
        task.get("lease_expires_at"),
        output_path,
    )


def complete_task(config: ClientConfig, task_path: Path, result_path: Path) -> None:
    """回传 AI 分析结果。

    功能说明：从任务文件读取服务端生成的 ID、哈希和租约，并与结果文件一起提交完成接口。
    参数 config：客户端连接参数。
    参数 task_path：领取命令生成的任务 JSON。
    参数 result_path：Codex 生成的结构化结果 JSON。
    返回值：无。
    """

    task = _read_object(task_path).get("task")
    if not isinstance(task, dict):
        raise ValueError("任务文件中没有可提交的 task 对象")
    result = _read_object(result_path)
    analysis_id = str(task.get("analysis_id") or "")
    payload = {
        "source_hash": task.get("source_hash"),
        "lease_token": task.get("lease_token"),
        "result": result,
    }
    _, response = request_json(config, "POST", f"/analysis-tasks/{analysis_id}/complete", payload)
    LOGGER.info("AI 分析结果回传完成：analysis_id=%s，response=%s", analysis_id, response)


def fail_task(config: ClientConfig, task_path: Path, error_message: str) -> None:
    """上报 AI 分析失败。

    功能说明：从任务文件读取服务端任务 ID 和租约，并提交可排查的失败原因。
    参数 config：客户端连接参数。
    参数 task_path：领取命令生成的任务 JSON。
    参数 error_message：本次分析失败原因。
    返回值：无。
    """

    task = _read_object(task_path).get("task")
    if not isinstance(task, dict):
        raise ValueError("任务文件中没有可上报失败的 task 对象")
    analysis_id = str(task.get("analysis_id") or "")
    payload = {"lease_token": task.get("lease_token"), "error": error_message}
    _, response = request_json(config, "POST", f"/analysis-tasks/{analysis_id}/fail", payload)
    LOGGER.info("AI 分析失败已上报：analysis_id=%s，response=%s", analysis_id, response)


def parse_args() -> argparse.Namespace:
    """解析任务客户端命令行参数。"""

    parser = argparse.ArgumentParser(description="查看、领取或回传京东竞品 AI 分析任务。")
    parser.add_argument("--env-file", type=Path, help="本地环境变量文件，默认读取 Skill 目录 .env。")
    parser.add_argument("--log-level", default="INFO", help="日志级别。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="查看最近的任务摘要。")
    list_parser.add_argument(
        "--status",
        choices=("pending", "processing", "completed", "failed"),
        help="仅显示指定状态的任务。",
    )
    list_parser.add_argument("--limit", type=int, default=20, help="最多显示的任务数量，默认 20。")

    claim_parser = subparsers.add_parser("claim", help="领取一条待分析任务。")
    claim_parser.add_argument("--output", type=Path, required=True, help="任务临时 JSON 输出路径。")

    complete_parser = subparsers.add_parser("complete", help="提交完成的 AI 分析结果。")
    complete_parser.add_argument("--task", type=Path, required=True, help="领取命令生成的任务 JSON。")
    complete_parser.add_argument("--result", type=Path, required=True, help="Codex 生成的结果 JSON。")

    fail_parser = subparsers.add_parser("fail", help="上报 AI 分析失败。")
    fail_parser.add_argument("--task", type=Path, required=True, help="领取命令生成的任务 JSON。")
    fail_parser.add_argument("--error", required=True, help="可排查的失败原因。")
    return parser.parse_args()


def main() -> None:
    """执行 AI 任务客户端。

    功能说明：加载配置并根据子命令查看任务、领取任务、回传结果或上报失败。
    返回值：无；成功结果写入文件或后端，错误写入标准错误并返回非零退出码。
    """

    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    config = load_config(args.env_file)
    if args.command == "list":
        list_tasks(config, args.status, args.limit)
    elif args.command == "claim":
        claim_task(config, args.output.expanduser().resolve())
    elif args.command == "complete":
        complete_task(config, args.task.expanduser().resolve(), args.result.expanduser().resolve())
    else:
        fail_task(config, args.task.expanduser().resolve(), args.error)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        LOGGER.error("AI 任务客户端执行失败：%s", error)
        sys.exit(1)
