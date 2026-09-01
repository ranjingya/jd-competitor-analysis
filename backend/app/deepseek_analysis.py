"""调用 DeepSeek 生成报告中的 AI 分析部分。"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from .deepseek_usage import append_usage_log
from .report_merge import validate_ai_result
from .schemas import AIAnalysisResult


LOGGER = logging.getLogger(__name__)
DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "assets" / "ai-analysis-prompt.md"
ANALYSIS_VERSION = "1.0"


class DeepSeekAnalysisError(RuntimeError):
    """DeepSeek 请求或响应不符合分析要求。"""


@dataclass(frozen=True)
class DeepSeekAnalysisConfig:
    """保存 DeepSeek 分析调用参数。"""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: int
    max_attempts: int
    pricing_path: Path
    usage_log_dir: Path | None
    prompt_path: Path = DEFAULT_PROMPT_PATH


class DeepSeekAnalyzer:
    """使用 OpenAI 兼容接口生成结构化分析结果。"""

    def __init__(self, config: DeepSeekAnalysisConfig) -> None:
        """初始化分析器。

        功能说明：读取分析规则并保存 DeepSeek 连接参数，不在初始化阶段发起网络请求。
        参数 config：API 密钥、模型、超时、重试次数、提示词、价格配置和用量日志路径。
        返回值：无。
        """

        if not config.api_key.strip():
            raise ValueError("DEEPSEEK_API_KEY 尚未配置")
        if not config.base_url.strip():
            raise ValueError("DEEPSEEK_BASE_URL 不能为空")
        if not config.model.strip():
            raise ValueError("DEEPSEEK_MODEL 不能为空")
        self.config = config
        self.model = config.model
        self.analysis_version = ANALYSIS_VERSION
        self.system_prompt = config.prompt_path.read_text(encoding="utf-8").strip()
        self.prompt_hash = hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()
        LOGGER.debug(
            "DeepSeek 分析规则已加载：model=%s，version=%s，prompt_hash=%s，path=%s",
            self.model,
            self.analysis_version,
            self.prompt_hash,
            config.prompt_path,
        )

    def analyze(
        self,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """分析后端准备好的确定性事实。

        功能说明：把结构化事实发送给 DeepSeek，要求返回 JSON，并完成基础 Schema 与业务字段校验。
        参数 payload：包含日期、商品对、本品 SPU 汇总值和五张来源表处理结果的 AI 输入。
        参数 context：可选任务、报告和业务周期标识，只写入独立用量日志。
        返回值：仅包含优缺点双摘要、findings 和 recommendations 的结构化结果。
        """

        started_at = perf_counter()
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": "请分析以下结构化事实，并严格返回 JSON 对象：\n"
                    + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        LOGGER.info("开始调用 DeepSeek：model=%s", self.model)
        last_error: DeepSeekAnalysisError | None = None
        remaining_attempts = self.config.max_attempts
        generation_attempt = 0
        while remaining_attempts > 0:
            generation_attempt += 1
            request_started_at = perf_counter()
            response, successful_attempt = self._request(request_body, remaining_attempts)
            remaining_attempts -= successful_attempt
            try:
                content = self._extract_content(response)
                parsed = json.loads(content)
                validated = AIAnalysisResult.model_validate(parsed).model_dump()
                result = validate_ai_result(validated)
            except (DeepSeekAnalysisError, json.JSONDecodeError, ValueError) as error:
                last_error = (
                    error
                    if isinstance(error, DeepSeekAnalysisError)
                    else DeepSeekAnalysisError(f"DeepSeek 返回结果不符合 JSON 契约：{error}")
                )
                self._record_usage(
                    response,
                    successful_attempt,
                    generation_attempt,
                    "invalid",
                    perf_counter() - request_started_at,
                    context,
                )
                if remaining_attempts == 0:
                    raise last_error from error
                LOGGER.warning(
                    "DeepSeek 返回结果校验失败，重新生成当前分析：generation=%s，"
                    "remaining_attempts=%s，原因=%s",
                    generation_attempt,
                    remaining_attempts,
                    last_error,
                )
                continue
            self._record_usage(
                response,
                successful_attempt,
                generation_attempt,
                "valid",
                perf_counter() - request_started_at,
                context,
            )
            LOGGER.info(
                "DeepSeek 分析完成：model=%s，findings=%s，recommendations=%s，耗时=%.3fs",
                self.model,
                len(result["findings"]),
                len(result["recommendations"]),
                perf_counter() - started_at,
            )
            return result
        raise last_error or DeepSeekAnalysisError("DeepSeek 返回结果校验失败")

    def _record_usage(
        self,
        response: dict[str, Any],
        request_attempt: int,
        generation_attempt: int,
        validation_status: str,
        duration_seconds: float,
        context: dict[str, Any] | None,
    ) -> None:
        """记录一次产生计费用量的 DeepSeek 响应。

        功能说明：无论模型结果是否通过契约校验，都保存本次响应的 Token 和费用；日志失败不影响分析。
        参数 response：DeepSeek 返回的完整响应对象。
        参数 request_attempt：本轮网络请求成功时对应的尝试次数。
        参数 generation_attempt：当前商品对结果生成次数。
        参数 validation_status：模型结果的契约校验状态。
        参数 duration_seconds：本次请求及响应校验耗时。
        参数 context：可选任务、报告和业务周期标识。
        返回值：无。
        """

        if self.config.usage_log_dir is None:
            return
        usage_context = dict(context or {})
        usage_context.update(
            {
                "generation_attempt": generation_attempt,
                "validation_status": validation_status,
            }
        )
        try:
            append_usage_log(
                self.config.usage_log_dir,
                self.config.pricing_path,
                response,
                self.model,
                duration_seconds,
                request_attempt,
                usage_context,
            )
        except Exception as error:
            LOGGER.warning("DeepSeek 用量日志写入失败，报告分析继续：%s", error)

    def _request(
        self,
        body: dict[str, Any],
        max_attempts: int,
    ) -> tuple[dict[str, Any], int]:
        """调用 Chat Completions 接口并处理有限重试。

        功能说明：在当前 AI 分析剩余尝试次数内处理网络、限流和服务端异常。
        参数 body：OpenAI 兼容的 Chat Completions 请求体。
        参数 max_attempts：当前分析可以使用的最大请求次数。
        返回值：响应 JSON 和本轮成功前实际使用的请求次数。
        """

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        request_data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        for attempt in range(1, max_attempts + 1):
            request = urllib.request.Request(
                url,
                data=request_data,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8")), attempt
            except urllib.error.HTTPError as error:
                message = self._http_error_message(error)
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt == max_attempts:
                    raise DeepSeekAnalysisError(message) from error
                LOGGER.warning(
                    "DeepSeek 请求失败，准备重试：attempt=%s/%s，原因=%s",
                    attempt,
                    max_attempts,
                    message,
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == max_attempts:
                    raise DeepSeekAnalysisError(f"DeepSeek 请求失败：{error}") from error
                LOGGER.warning(
                    "DeepSeek 请求异常，准备重试：attempt=%s/%s，原因=%s",
                    attempt,
                    max_attempts,
                    error,
                )
            time.sleep(min(2 ** (attempt - 1), 4))
        raise DeepSeekAnalysisError("DeepSeek 请求未返回结果")

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:
        """从 Chat Completions 响应中提取文本内容。"""

        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise DeepSeekAnalysisError("DeepSeek 响应缺少 choices[0].message.content") from error
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekAnalysisError("DeepSeek 返回了空内容")
        return content.strip()

    @staticmethod
    def _http_error_message(error: urllib.error.HTTPError) -> str:
        """提取不包含密钥的 HTTP 错误信息。"""

        try:
            detail = error.read().decode("utf-8")[:1000]
        except Exception:
            detail = str(error.reason)
        return f"DeepSeek HTTP {error.code}：{detail}"
