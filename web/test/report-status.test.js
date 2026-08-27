import assert from "node:assert/strict";
import test from "node:test";

import { reportStatusModel } from "../src/report-status.js";


test("周报缺天时生成覆盖率和逐日原因", () => {
  const model = reportStatusModel({
    report_status: "ready",
    meta: {
      period: "2026-08-17 至 2026-08-23",
      period_days: 7,
      available_days: 5,
      missing_days: ["2026-08-19", "2026-08-21"]
    }
  });

  assert.equal(model.title, "数据不完整 · 5/7 天可用");
  assert.equal(model.details.length, 2);
  assert.match(model.detail, /8月19日/);
  assert.match(model.detail, /8月21日/);
});

test("完整且 AI 已完成的报告无需展示异常状态条", () => {
  assert.equal(reportStatusModel({ report_status: "ready", meta: {} }), null);
});

test("AI 失败时保留基础报告并提供局部异常说明", () => {
  const model = reportStatusModel({
    report_status: "ai_failed",
    meta: { period: "2026-08-21", period_start: "2026-08-21" }
  });

  assert.equal(model.tone, "danger");
  assert.equal(model.title, "AI 分析失败 · 基础报告可用");
  assert.equal(model.details[0].label, "AI 失败");
});
