"""计算并追加 DeepSeek 单次请求用量日志。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
BEIJING_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")
TOKENS_PER_MILLION = Decimal("1000000")


def _non_negative_integer(value: Any) -> int:
    """把用量字段转换为非负整数。"""

    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def normalize_usage(usage: Any) -> dict[str, int]:
    """标准化 DeepSeek 返回的 Token 用量。

    功能说明：兼容顶层缓存字段和详情对象字段，并保留推理 Token；推理 Token
    已包含在输出 Token 中，不参与额外计费。
    参数 usage：DeepSeek 响应中的原始 usage 对象。
    返回值：固定六字段的非负整数用量对象。
    """

    selected_usage = usage if isinstance(usage, dict) else {}
    prompt_tokens = _non_negative_integer(selected_usage.get("prompt_tokens"))
    completion_tokens = _non_negative_integer(selected_usage.get("completion_tokens"))
    prompt_details = selected_usage.get("prompt_tokens_details")
    completion_details = selected_usage.get("completion_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = completion_details if isinstance(completion_details, dict) else {}
    cache_hit_tokens = _non_negative_integer(
        selected_usage.get(
            "prompt_cache_hit_tokens",
            prompt_details.get("cached_tokens"),
        )
    )
    cache_miss_value = selected_usage.get("prompt_cache_miss_tokens")
    cache_miss_tokens = (
        _non_negative_integer(cache_miss_value)
        if cache_miss_value is not None
        else max(prompt_tokens - cache_hit_tokens, 0)
    )
    return {
        "prompt_tokens": prompt_tokens,
        "cache_hit_tokens": cache_hit_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": _non_negative_integer(
            completion_details.get("reasoning_tokens")
        ),
        "total_tokens": _non_negative_integer(
            selected_usage.get("total_tokens", prompt_tokens + completion_tokens)
        ),
    }


def load_pricing(pricing_path: Path, model: str) -> dict[str, Any] | None:
    """读取指定模型的基础价格快照。

    功能说明：从可替换 JSON 配置中读取人民币百万 Token 单价和固定倍率；未知模型
    返回空值，使请求继续完成但不估算费用。
    参数 pricing_path：DeepSeek 价格配置文件路径。
    参数 model：响应或请求使用的模型标识。
    返回值：包含币种、单价、倍率和来源的价格快照；未配置模型时返回空值。
    """

    data = json.loads(pricing_path.read_text(encoding="utf-8"))
    models = data.get("models") if isinstance(data, dict) else None
    model_pricing = models.get(model) if isinstance(models, dict) else None
    if not isinstance(model_pricing, dict):
        return None
    return {
        "currency": str(data.get("currency") or "CNY"),
        "unit": str(data.get("unit") or "million_tokens"),
        "multiplier": float(data.get("multiplier") or 1),
        "cache_hit_input": float(model_pricing["cache_hit_input"]),
        "cache_miss_input": float(model_pricing["cache_miss_input"]),
        "output": float(model_pricing["output"]),
        "source": data.get("source"),
        "source_checked_at": data.get("source_checked_at"),
    }


def estimate_cost(usage: dict[str, int], pricing: dict[str, Any]) -> float:
    """根据 Token 用量和价格快照估算人民币费用。

    功能说明：分别计算缓存命中输入、缓存未命中输入和全部输出费用，再应用配置倍率。
    参数 usage：标准化后的 Token 用量。
    参数 pricing：当前模型的百万 Token 单价快照。
    返回值：保留九位小数的估算费用。
    """

    cost = (
        Decimal(usage["cache_hit_tokens"]) * Decimal(str(pricing["cache_hit_input"]))
        + Decimal(usage["cache_miss_tokens"]) * Decimal(str(pricing["cache_miss_input"]))
        + Decimal(usage["completion_tokens"]) * Decimal(str(pricing["output"]))
    ) / TOKENS_PER_MILLION
    cost *= Decimal(str(pricing["multiplier"]))
    return float(cost.quantize(Decimal("0.000000001")))


def append_usage_log(
    log_dir: Path,
    pricing_path: Path,
    response: dict[str, Any],
    request_model: str,
    duration_seconds: float,
    attempt: int,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """追加一次 DeepSeek 成功响应的用量日志。

    功能说明：标准化响应 usage、按基础价格估算费用，并以单行 JSON 原子追加到
    按北京时间月份切分的日志文件。日志不保存提示词、payload 或模型正文。
    参数 log_dir：宿主机挂载的数据日志目录。
    参数 pricing_path：DeepSeek 价格配置文件路径。
    参数 response：DeepSeek 完整响应对象。
    参数 request_model：请求使用的模型标识。
    参数 duration_seconds：本次请求总耗时。
    参数 attempt：成功响应对应的请求次数。
    参数 context：可选报告、任务、周期和商品对标识。
    返回值：已经写入日志的结构化记录。
    """

    now = datetime.now(BEIJING_TIMEZONE)
    model = str(response.get("model") or request_model)
    usage_raw = response.get("usage")
    has_usage = isinstance(usage_raw, dict)
    usage = normalize_usage(usage_raw)
    pricing = load_pricing(pricing_path, model)
    record = {
        "timestamp": now.isoformat(timespec="seconds"),
        **dict(context or {}),
        "response_id": response.get("id"),
        "model": model,
        "attempt": attempt,
        "status": "success" if has_usage else "usage_missing",
        "duration_seconds": round(duration_seconds, 3),
        "usage": usage,
        "pricing": pricing,
        "estimated_cost": (
            estimate_cost(usage, pricing)
            if has_usage and pricing is not None
            else None
        ),
        "currency": pricing["currency"] if pricing is not None else None,
        "system_fingerprint": response.get("system_fingerprint"),
        "usage_raw": usage_raw if has_usage else None,
    }
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"deepseek-usage-{now:%Y-%m}.jsonl"
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    descriptor = os.open(log_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o640)
    try:
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)
    cost_text = (
        f"{record['estimated_cost']:.9f}"
        if record["estimated_cost"] is not None
        else "unknown"
    )
    LOGGER.info(
        "DeepSeek 用量已记录：tokens=%s，cost=%s %s，file=%s",
        usage["total_tokens"],
        cost_text,
        record["currency"] or "unknown",
        log_path,
    )
    return record
