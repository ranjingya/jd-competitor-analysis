"""调用 DeepSeek 生成报告中的 AI 分析部分。"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from .report_merge import validate_ai_result
from .schemas import AIAnalysisResult


LOGGER = logging.getLogger(__name__)
DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[1] / "assets" / "ai-analysis-prompt.md"


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
    prompt_path: Path = DEFAULT_PROMPT_PATH


class DeepSeekAnalyzer:
    """使用 OpenAI 兼容接口生成结构化分析结果。"""

    def __init__(self, config: DeepSeekAnalysisConfig) -> None:
        """初始化分析器。

        功能说明：读取分析规则并保存 DeepSeek 连接参数，不在初始化阶段发起网络请求。
        参数 config：API 密钥、模型、超时、重试次数和提示词路径。
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
        self.system_prompt = config.prompt_path.read_text(encoding="utf-8").strip()
        LOGGER.info("DeepSeek 分析规则已加载：model=%s，path=%s", self.model, config.prompt_path)

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        """分析后端准备好的确定性事实。

        功能说明：把结构化事实发送给 DeepSeek，要求返回 JSON，并完成基础 Schema 与业务字段校验。
        参数 payload：包含日期、商品对、本品 SPU 汇总值和五张来源表处理结果的 AI 输入。
        返回值：仅包含 summary、findings 和 recommendations 的结构化结果。
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
        response = self._request(request_body)
        content = self._extract_content(response)
        try:
            parsed = json.loads(content)
            validated = AIAnalysisResult.model_validate(parsed).model_dump()
            result = validate_ai_result(validated)
        except (json.JSONDecodeError, ValueError) as error:
            raise DeepSeekAnalysisError(f"DeepSeek 返回结果不符合 JSON 契约：{error}") from error
        LOGGER.info(
            "DeepSeek 分析完成：model=%s，findings=%s，recommendations=%s，耗时=%.3fs",
            self.model,
            len(result["findings"]),
            len(result["recommendations"]),
            perf_counter() - started_at,
        )
        return result

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        """调用 Chat Completions 接口并处理有限重试。"""

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        request_data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        for attempt in range(1, self.config.max_attempts + 1):
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
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                message = self._http_error_message(error)
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt == self.config.max_attempts:
                    raise DeepSeekAnalysisError(message) from error
                LOGGER.warning(
                    "DeepSeek 请求失败，准备重试：attempt=%s/%s，原因=%s",
                    attempt,
                    self.config.max_attempts,
                    message,
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == self.config.max_attempts:
                    raise DeepSeekAnalysisError(f"DeepSeek 请求失败：{error}") from error
                LOGGER.warning(
                    "DeepSeek 请求异常，准备重试：attempt=%s/%s，原因=%s",
                    attempt,
                    self.config.max_attempts,
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
