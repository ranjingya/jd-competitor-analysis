"""测试 DeepSeek 结构化分析客户端。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.deepseek_analysis import (
    DeepSeekAnalysisConfig,
    DeepSeekAnalysisError,
    DeepSeekAnalyzer,
)


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

    def _analyzer(self, prompt_path: Path) -> DeepSeekAnalyzer:
        """创建使用临时提示词的分析器。"""

        return DeepSeekAnalyzer(
            DeepSeekAnalysisConfig(
                api_key="test-key",
                base_url="https://api.deepseek.com",
                model="deepseek-v4-pro",
                timeout_seconds=30,
                max_attempts=1,
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
        """缺少输出字段的模型响应不得进入报告。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "prompt.md"
            prompt_path.write_text("请只返回 JSON。", encoding="utf-8")
            analyzer = self._analyzer(prompt_path)
            response = {"choices": [{"message": {"content": "{}"}}]}
            with patch(
                "app.deepseek_analysis.urllib.request.urlopen",
                return_value=FakeResponse(response),
            ):
                with self.assertRaisesRegex(DeepSeekAnalysisError, "JSON 契约"):
                    analyzer.analyze({"facts": {}})


if __name__ == "__main__":
    unittest.main()
