"""验证宿主机最终通知；所有 Docker 和 HTTP 调用均使用本地替身。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/run-daily-analysis.sh"


@unittest.skipUnless(shutil.which("jq"), "需要 jq")
class DailyNotificationScriptTest(unittest.TestCase):
    """检查通知分流、重试汇总和通知测试隔离。"""

    def setUp(self) -> None:
        """建立隔离的部署目录及命令替身，不接触项目环境文件。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copyfile(SCRIPT, self.root / "scripts/run-daily-analysis.sh")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "TEST_ROOT": str(self.root)}
        (self.root / ".env").write_text(
            "HEALTHCHECKS_PING_URL=https://example.invalid/ping/check\n"
            "LARK_COMPLETION_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/test\n"
            "LARK_COMPLETION_WEBHOOK_SECRET=test\nDASHBOARD_URL=https://example.invalid/\n"
            "LARK_APP_ID=test\nLARK_APP_SECRET=test\nLARK_ALERT_OPEN_ID=ou_test\n"
        )
        self.command("curl", '''
import json, os, sys
from pathlib import Path
root = Path(os.environ["TEST_ROOT"])
url = sys.argv[-1]
body = sys.stdin.read() if "--data-binary" in sys.argv else ""
with (root / "requests.jsonl").open("a") as file:
    file.write(json.dumps({"url": url, "body": body}) + "\\n")
print(json.dumps({"code": 0, "tenant_access_token": "test-token"}))
''')
        self.command("docker", '''
import json, os, sys
from pathlib import Path
root = Path(os.environ["TEST_ROOT"])
with (root / "docker.jsonl").open("a") as file:
    file.write(json.dumps(sys.argv[1:]) + "\\n")
if "--notification-file" in sys.argv:
    counter = root / "attempt"
    attempt = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(attempt))
    data = json.loads((root / ("attempt-" + str(attempt) + ".json")).read_text())
    path = Path(sys.argv[sys.argv.index("--notification-file") + 1])
    (root / "data/logs" / path.name).write_text(json.dumps(data["summary"]))
    sys.exit(data["exit_code"])
''')
        self.command("sleep", "pass\n")
        self.command("date", '''
import sys
values = {"+%u": "1", "+%d": "01", "+%s": "1788220800", "+%Y-%m-%d": "2026-09-01"}
print(values.get(sys.argv[1], "2026-09-01 12:00:00"))
''')

    def command(self, name: str, source: str) -> None:
        """写入当前测试专用的可执行替身。"""
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def item(self, day: str, pair: str, status: str) -> dict:
        """构造通知使用的最小业务结果。"""
        return {"date": day, "self_spu": pair, "competitor_spu": "200", "status": status}

    def attempt(self, number: int, items: list, exit_code: int = 0) -> None:
        """保存 Docker 替身某次执行的返回值。"""
        (self.root / f"attempt-{number}.json").write_text(json.dumps({
            "exit_code": exit_code, "summary": {"total_pairs": 2, "results": items},
        }))

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        """执行隔离脚本，返回退出状态及日志。"""
        return subprocess.run(
            ["/bin/bash", str(self.root / "scripts/run-daily-analysis.sh"), *args],
            env=self.env, capture_output=True, text=True, errors="replace", timeout=20,
        )

    def requests(self) -> list:
        """读取替身捕获的 HTTP 请求。"""
        path = self.root / "requests.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_no_data_allows_completion_weekly_and_monthly(self) -> None:
        """整日无数据仍发送完成通知，并执行计划中的周月报。"""
        self.attempt(1, [self.item("2026-08-31", "100", "no_data"),
                         self.item("2026-08-30", "100", "existing")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        requests = self.requests()
        group = [r for r in requests if "/hook/" in r["url"]]
        self.assertEqual(len(group), 1)
        self.assertIn("2026-08-31：新增 0，无数据 1", group[0]["body"])
        self.assertNotIn("2026-08-30", group[0]["body"])
        self.assertFalse(any("/messages" in r["url"] or "/fail" in r["url"] for r in requests))
        commands = (self.root / "docker.jsonl").read_text()
        self.assertIn("weekly-report-run", commands)
        self.assertIn("monthly-report-run", commands)
        self.assertEqual(list((self.root / "data/logs").glob(".daily-notification.*")), [])

    def test_retry_keeps_first_attempt_new_reports_without_duplicates(self) -> None:
        """第一次新增、第二次已有的报告仍只计入一次新增。"""
        self.attempt(1, [self.item("2026-08-31", "100", "ready"),
                         self.item("2026-08-31", "101", "failed")], 1)
        self.attempt(2, [self.item("2026-08-31", "100", "existing"),
                         self.item("2026-08-31", "101", "ready")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        group = next(r for r in self.requests() if "/hook/" in r["url"])
        self.assertIn("2026-08-31：新增 2", group["body"])
        self.assertNotIn("补", group["body"])

    def test_ai_failure_sends_private_only_and_does_not_retry_batch(self) -> None:
        """AI 失败只发送私聊告警，不调用群 Webhook。"""
        self.attempt(1, [self.item("2026-08-31", "100", "ai_failed")], 14)
        result = self.run_script()
        self.assertEqual(result.returncode, 14, result.stderr)
        requests = self.requests()
        private = [r for r in requests if "/messages" in r["url"]]
        self.assertEqual(len(private), 1)
        self.assertEqual(json.loads(private[0]["body"])["receive_id"], "ou_test")
        self.assertFalse(any("/hook/" in r["url"] for r in requests))
        self.assertEqual((self.root / "attempt").read_text(), "1")

    def test_private_preview_does_not_call_docker_hc_or_group(self) -> None:
        """测试卡片只通过自建应用私聊发送，不启动任务或上报监控。"""
        fixture = self.root / "preview.json"
        fixture.write_text(json.dumps({"total_pairs": 2, "results": [
            self.item("2026-08-31", "100", "ready"),
            self.item("2026-08-31", "101", "no_data"),
        ]}))
        result = self.run_script("--test-notification-private", str(fixture))
        self.assertEqual(result.returncode, 0, result.stderr)
        requests = self.requests()
        self.assertEqual(len(requests), 2)
        self.assertFalse((self.root / "docker.jsonl").exists())
        self.assertTrue(all("/auth/" in r["url"] or "/messages" in r["url"] for r in requests))
        message = json.loads(requests[-1]["body"])
        self.assertEqual(message["receive_id"], "ou_test")
        card = json.loads(message["content"])
        self.assertIn("通知测试", card["header"]["title"]["content"])
        self.assertIn("2026-08-31：新增 1，无数据 1", message["content"])
        self.assertIn("生成时间：2026-09-01 12:00:00（UTC+8）", message["content"])

    def test_existing_only_has_no_date_rows(self) -> None:
        """全部已有时不列出日期结果。"""
        self.attempt(1, [self.item("2026-08-31", "100", "existing")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = next(r["body"] for r in self.requests() if "/hook/" in r["url"])
        self.assertIn("本次无新增", message)
        self.assertNotIn("2026-08-31", message)
