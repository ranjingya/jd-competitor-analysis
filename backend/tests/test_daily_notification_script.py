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
    kind = "week" if "weekly-report-run" in sys.argv else "month" if "monthly-report-run" in sys.argv else "day"
    prefix = "" if kind == "day" else kind + "-"
    counter = root / (prefix + "attempt")
    attempt = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(attempt))
    fixture = root / (prefix + "attempt-" + str(attempt) + ".json")
    data = json.loads(fixture.read_text()) if fixture.exists() else {
        "exit_code": 0, "summary": {"total_pairs": 0, "results": []}}
    data["summary"]["granularity"] = kind
    path = Path(sys.argv[sys.argv.index("--notification-file") + 1])
    (root / "data/logs" / path.name).write_text(json.dumps(data["summary"]))
    sys.exit(data["exit_code"])
''')
        self.command("sleep", "pass\n")
        self.command("date", '''
import sys
values = {"+%u": "2", "+%d": "08", "+%s": "1788220800", "+%Y-%m-%d": "2026-09-08", "+%m-%d %H:%M": "09-08 12:00"}
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

    def period_attempt(self, kind: str, number: int, statuses: list[str], exit_code: int = 0) -> None:
        """提供指定周月批次的执行结果，默认周期覆盖八月最后一周或八月全月。"""
        (self.root / f"{kind}-attempt-{number}.json").write_text(json.dumps({
            "exit_code": exit_code,
            "summary": {"total_pairs": len(statuses), "results": [
                {"start_date": "2026-08-31" if kind == "week" else "2026-08-01",
                 "end_date": "2026-09-06" if kind == "week" else "2026-08-31",
                 "self_spu": str(index), "competitor_spu": "200", "status": status}
                for index, status in enumerate(statuses)
            ]},
        }))

    def requests(self) -> list:
        """读取替身捕获的 HTTP 请求。"""
        path = self.root / "requests.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_no_data_allows_completion_weekly_and_monthly(self) -> None:
        """整日无数据仍执行周月报、上报监控成功并发送昨日日报状态。"""
        self.attempt(1, [self.item("2026-09-07", "100", "no_data"),
                         self.item("2026-08-30", "100", "existing")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        requests = self.requests()
        group = [r for r in requests if "/hook/" in r["url"]]
        self.assertEqual(len(group), 1)
        self.assertIn("09-07：暂无数据", group[0]["body"])
        self.assertNotIn("08-30", group[0]["body"])
        self.assertTrue(any(r["url"].endswith("/ping/check") for r in requests))
        self.assertFalse(any("/messages" in r["url"] or "/fail" in r["url"] for r in requests))
        commands = (self.root / "docker.jsonl").read_text()
        self.assertIn("weekly-report-run", commands)
        self.assertIn("monthly-report-run", commands)
        self.assertEqual(list((self.root / "data/logs").glob(".daily-notification.*")), [])
        self.assertEqual(list((self.root / "data/logs").glob(".period-notification.*")), [])

    def test_retry_keeps_first_attempt_new_reports_without_duplicates(self) -> None:
        """第一次新增、第二次已有的报告仍只计入一次新增。"""
        self.attempt(1, [self.item("2026-08-31", "100", "ready"),
                         self.item("2026-08-31", "101", "failed")], 1)
        self.attempt(2, [self.item("2026-08-31", "100", "existing"),
                         self.item("2026-08-31", "101", "ready")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        group = next(r for r in self.requests() if "/hook/" in r["url"])
        self.assertIn("08-31：成功 2 份", group["body"])
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
        commands = (self.root / "docker.jsonl").read_text()
        self.assertIn("weekly-report-run", commands)
        self.assertIn("monthly-report-run", commands)

    def test_period_success_is_listed_only_when_generated(self) -> None:
        """周二正常补上周上月，通知只列实际新增周期而不列不全或已有数量。"""
        self.attempt(1, [self.item("2026-09-07", "100", "existing")])
        self.period_attempt("week", 1, ["ready", "existing", "incomplete"])
        self.period_attempt("month", 1, ["ready", "incomplete"])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = next(r["body"] for r in self.requests() if "/hook/" in r["url"])
        self.assertIn("周报\\n08-31～09-06：成功 1 份", message)
        self.assertIn("月报\\n08-01～08-31：成功 1 份", message)
        self.assertIn("09-07：报告已生成", message)
        self.assertNotIn("本次无新增", message)
        self.assertNotIn("incomplete", message)
        self.assertNotIn("不全", message)

    def test_incomplete_and_existing_periods_are_hidden(self) -> None:
        """周月全部已有或不全时，通知不出现周报月报文字及对应周期。"""
        self.attempt(1, [self.item("2026-09-07", "100", "ready")])
        self.period_attempt("week", 1, ["incomplete", "existing"])
        self.period_attempt("month", 1, ["incomplete"])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = next(r["body"] for r in self.requests() if "/hook/" in r["url"])
        self.assertNotIn("周报", message)
        self.assertNotIn("月报", message)
        self.assertNotIn("2026-08-31", message)

    def test_period_retry_counts_success_once(self) -> None:
        """周报重试保留第一次新增结果且月报继续执行。"""
        self.attempt(1, [])
        self.period_attempt("week", 1, ["ready", "failed"], 1)
        self.period_attempt("week", 2, ["existing", "ready"])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = next(r["body"] for r in self.requests() if "/hook/" in r["url"])
        self.assertIn("08-31～09-06：成功 2 份", message)
        self.assertNotIn("月报", message)

    def test_failed_week_does_not_block_month_or_send_group(self) -> None:
        """周报 AI 失败只告警私聊，月报仍独立执行。"""
        self.attempt(1, [])
        self.period_attempt("week", 1, ["ai_failed"], 14)
        self.period_attempt("month", 1, ["ready"])
        result = self.run_script()
        self.assertEqual(result.returncode, 14, result.stderr)
        self.assertEqual((self.root / "week-attempt").read_text(), "1")
        self.assertEqual((self.root / "month-attempt").read_text(), "1")
        self.assertFalse(any("/hook/" in r["url"] for r in self.requests()))
        self.assertTrue(any("/messages" in r["url"] for r in self.requests()))

    def test_daily_failure_remains_failure_after_successful_periods(self) -> None:
        """日报普通失败重试耗尽后继续周月报，最终退出码和失败路由保持正确。"""
        self.attempt(1, [], 1)
        self.attempt(2, [], 1)
        self.period_attempt("week", 1, ["ready"])
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual((self.root / "month-attempt").read_text(), "1")
        self.assertFalse(any("/hook/" in r["url"] for r in self.requests()))

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
        self.assertIn("08-31：成功 1 份", message["content"])
        self.assertNotIn("无数据", message["content"])
        self.assertIn("生成时间：09-08 12:00", message["content"])

    def test_existing_only_sends_group_notification(self) -> None:
        """全部已有时发送昨日日报已生成，监控仍收到成功请求。"""
        self.attempt(1, [self.item("2026-09-07", "100", "existing")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = next(r["body"] for r in self.requests() if "/hook/" in r["url"])
        self.assertIn("09-07：报告已生成", message)
        self.assertTrue(any(r["url"].endswith("/ping/check") for r in self.requests()))

    def test_private_period_preview_shows_only_success_count(self) -> None:
        """单独预览周报通知时，只展示成功数量。"""
        self.period_attempt("week", 1, ["ready", "incomplete"])
        data = json.loads((self.root / "week-attempt-1.json").read_text())["summary"]
        data["granularity"] = "week"
        preview = self.root / "period-preview.json"
        preview.write_text(json.dumps(data))
        result = self.run_script("--test-notification-private", str(preview))
        self.assertEqual(result.returncode, 0, result.stderr)
        content = json.loads(self.requests()[-1]["body"])["content"]
        self.assertNotIn("商品对", content)
        self.assertIn("周报\\n08-31～09-06：成功 1 份", content)
        self.assertNotIn("月报", content)

    def test_mixed_days_show_only_successful_dates(self) -> None:
        """展示昨天无数据及历史成功报告，隐藏历史已有日期。"""
        self.attempt(1, [self.item("2026-09-07", "100", "no_data"),
                         self.item("2026-09-06", "100", "ready"),
                         self.item("2026-09-06", "101", "no_data"),
                         self.item("2026-09-05", "100", "ready"),
                         self.item("2026-09-05", "101", "ready"),
                         self.item("2026-09-04", "100", "existing")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        body = next(r["body"] for r in self.requests() if "/hook/" in r["url"])
        card = json.loads(body)["card"]
        self.assertEqual(card["header"]["title"]["content"], "京东竞品分析 · 报告更新")
        self.assertEqual(card["elements"][0]["text"]["content"], "日报\n09-07：暂无数据\n09-06：成功 1 份\n09-05：成功 2 份")
        self.assertNotIn("09-04", body)
        self.assertNotIn("商品对", body)
        self.assertEqual(card["elements"][2]["actions"][0]["text"]["content"], "查看报告")

    def test_empty_daily_preview_shows_not_generated(self) -> None:
        """日报没有处理记录时展示暂未生成，不误报数仓无数据。"""
        fixture = self.root / "preview.json"
        fixture.write_text(json.dumps({"total_pairs": 0, "results": []}))
        result = self.run_script("--test-notification-private", str(fixture))
        self.assertEqual(result.returncode, 0, result.stderr)
        message = json.loads(self.requests()[-1]["body"])
        self.assertIn("09-07：暂未生成", message["content"])

    def test_mixed_target_day_counts_new_reports_only(self) -> None:
        """昨天混合状态时只计本次成功份数，不把已有和无数据计入成功。"""
        self.attempt(1, [self.item("2026-09-07", "100", "ready"),
                         self.item("2026-09-07", "101", "existing"),
                         self.item("2026-09-07", "102", "no_data")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = next(r["body"] for r in self.requests() if "/hook/" in r["url"])
        self.assertIn("09-07：成功 1 份", message)
        self.assertNotIn("报告已生成", message)

    def test_existing_and_no_data_target_day_shows_available_report(self) -> None:
        """已有报告与无数据并存时展示报告已生成。"""
        self.attempt(1, [self.item("2026-09-07", "100", "existing"),
                         self.item("2026-09-07", "101", "no_data")])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = next(r["body"] for r in self.requests() if "/hook/" in r["url"])
        self.assertIn("09-07：报告已生成", message)
