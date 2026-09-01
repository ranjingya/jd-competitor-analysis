"""测试 DeepSeek 结构化分析客户端。"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.deepseek_analysis import (
    DeepSeekAnalysisConfig,
    DeepSeekAnalysisError,
    DeepSeekAnalyzer,
)


PRICING_PATH = Path(__file__).resolve().parents[2] / "data" / "deepseek-pricing.json"


class FakeResponse:
    """模拟 urllib 返回的上下文响应。"""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        """返回编码后的 JSON 响应。"""

        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class DeepSeekAnalyzerTest(unittest.TestCase):
    """验证请求参数和返回契约。"""

    def _analyzer(
        self,
        prompt_path: Path,
        usage_log_dir: Path | None = None,
        max_attempts: int = 1,
    ) -> DeepSeekAnalyzer:
        """创建使用临时提示词和指定总尝试次数的分析器。"""

        return DeepSeekAnalyzer(
            DeepSeekAnalysisConfig(
                api_key="test-key",
                base_url="https://api.deepseek.com",
                model="deepseek-v4-pro",
                timeout_seconds=30,
                max_attempts=max_attempts,
                pricing_path=PRICING_PATH,
                usage_log_dir=usage_log_dir,
                prompt_path=prompt_path,
            )
        )

    def test_analyze_returns_valid_contract(self) -> None:
        """有效 JSON 响应应转换为固定三字段结果。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("请只返回 JSON。", encoding="utf-8")
            analyzer = self._analyzer(prompt_path)
            model_result = {
                "summary": {
                    "advantage": {"brief": "流量领先", "detail": ["本品流量规模领先。"]},
                    "weakness": {"brief": "转化落后", "detail": ["本品转化效率落后。"]},
                },
                "findings": [],
                "recommendations": [],
            }
            response = {"choices": [{"message": {"content": json.dumps(model_result)}}]}
            with patch(
                "app.deepseek_analysis.urllib.request.urlopen",
                return_value=FakeResponse(response),
            ) as urlopen:
                result = analyzer.analyze({"facts": {"visitors": 10}})

        request = urlopen.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, model_result)
        self.assertEqual(request_body["model"], "deepseek-v4-pro")
        self.assertEqual(request_body["response_format"], {"type": "json_object"})
        self.assertNotIn("test-key", request_body["messages"][1]["content"])

    def test_invalid_content_is_rejected(self) -> None:
        """尝试次数耗尽后缺少输出字段的模型响应不得进入报告。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("请只返回 JSON。", encoding="utf-8")
            analyzer = self._analyzer(prompt_path)
            response = {"choices": [{"message": {"content": "{}"}}]}
            with patch(
                "app.deepseek_analysis.urllib.request.urlopen",
                return_value=FakeResponse(response),
            ) as urlopen:
                with self.assertRaisesRegex(DeepSeekAnalysisError, "JSON 契约"):
                    analyzer.analyze({"facts": {}})
            self.assertEqual(urlopen.call_count, 1)

    def test_invalid_content_retries_only_current_analysis(self) -> None:
        """第一次结果不符合契约时应只重新生成当前 AI 分析。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("请只返回 JSON。", encoding="utf-8")
            analyzer = self._analyzer(prompt_path, max_attempts=2)
            model_result = {
                "summary": {
                    "advantage": {"brief": "流量领先", "detail": ["本品流量规模领先。"]},
                    "weakness": {"brief": "转化落后", "detail": ["本品转化效率落后。"]},
                },
                "findings": [],
                "recommendations": [],
            }
            responses = [
                FakeResponse({"choices": [{"message": {"content": "{}"}}]}),
                FakeResponse(
                    {"choices": [{"message": {"content": json.dumps(model_result)}}]}
                ),
            ]
            with patch(
                "app.deepseek_analysis.urllib.request.urlopen",
                side_effect=responses,
            ) as urlopen:
                result = analyzer.analyze({"facts": {"visitors": 10}})

        self.assertEqual(result, model_result)
        self.assertEqual(urlopen.call_count, 2)

    def test_usage_and_estimated_cost_are_written_to_monthly_jsonl(self) -> None:
        """成功响应应记录 Token、基础价格快照和估算费用。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            prompt_path = temp_path / "prompt.md"
            prompt_path.write_text("请只返回 JSON。", encoding="utf-8")
            usage_log_dir = temp_path / "logs"
            analyzer = self._analyzer(prompt_path, usage_log_dir)
            model_result = {
                "summary": {
                    "advantage": {"brief": "流量领先", "detail": ["本品流量规模领先。"]},
                    "weakness": {"brief": "转化落后", "detail": ["本品转化效率落后。"]},
                },
                "findings": [],
                "recommendations": [],
            }
            response = {
                "id": "response-1",
                "model": "deepseek-v4-pro",
                "system_fingerprint": "fingerprint-1",
                "choices": [{"message": {"content": json.dumps(model_result)}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 137,
                    "total_tokens": 147,
                    "prompt_tokens_details": {"cached_tokens": 0},
                    "completion_tokens_details": {"reasoning_tokens": 124},
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 10,
                },
            }
            with patch(
                "app.deepseek_analysis.urllib.request.urlopen",
                return_value=FakeResponse(response),
            ):
                analyzer.analyze(
                    {"facts": {"visitors": 10}},
                    {"analysis_id": "analysis-1", "report_id": "report-1"},
                )
            log_paths = list(usage_log_dir.glob("deepseek-usage-*.jsonl"))
            record = json.loads(log_paths[0].read_text(encoding="utf-8"))
            file_mode = stat.S_IMODE(log_paths[0].stat().st_mode)

        self.assertEqual(len(log_paths), 1)
        self.assertEqual(record["analysis_id"], "analysis-1")
        self.assertEqual(record["usage"]["reasoning_tokens"], 124)
        self.assertEqual(file_mode, 0o644)
        self.assertEqual(record["pricing"]["multiplier"], 1.0)
        self.assertEqual(record["estimated_cost"], 0.000852)
        self.assertEqual(record["generation_attempt"], 1)
        self.assertEqual(record["validation_status"], "valid")


if __name__ == "__main__":
    unittest.main()
