import assert from "node:assert/strict";
import test from "node:test";
import { renderPeriodPicker } from "../src/period-picker.js";

/**
 * 功能说明：用最小 DOM 替身捕获日历实际渲染的 HTML。
 * 参数 t：测试上下文，用于恢复全局 document。
 * 参数 granularity：日、周或月粒度。
 * 参数 entries：供日历展示的报告索引。
 * 参数 selectedId：当前已选报告标识。
 * 参数 context：当前浏览月份或年份。
 * 参数 contexts：允许浏览的月份或年份。
 * 参数 selectedPeriod：独立于报告存在性的已选日期范围。
 * 返回值：面板 HTML 和渲染配置。
 */
function renderPanel(t, granularity, entries, selectedId, context, contexts, selectedPeriod = null) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "document");
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, "document", previous);
    else delete globalThis.document;
  });
  const content = { replaceChildren(panel) { this.panel = panel; } };
  globalThis.document = {
    createElement: () => ({ innerHTML: "", querySelectorAll: () => [] })
  };
  const options = {
    container: {
      innerHTML: "",
      querySelector: (selector) => selector === "[data-selector-content]" ? content : null,
      querySelectorAll: () => []
    },
    index: { reports: { [granularity]: entries } },
    activeGranularity: granularity,
    selectedReportIds: { [granularity]: selectedId },
    selectedPeriods: selectedPeriod ? { [granularity]: selectedPeriod } : {},
    reportCounts: { [granularity]: entries.length },
    periodContexts: { [granularity]: contexts },
    pickerState: { open: true, contexts: { [granularity]: context } }
  };
  renderPeriodPicker(options);
  return { html: content.panel.innerHTML, options };
}

function report(report_id, start_date, end_date = start_date, extra = {}) {
  return { report_id, start_date, end_date, status: "ready", ...extra };
}

function selectedIds(html) {
  const buttons = html.match(/<button\b[^>]*>/g) || [];
  for (const button of buttons) {
    if (!button.includes("data-report-id=")) continue;
    const selected = button.includes('aria-pressed="true"');
    assert.equal(button.includes(" is-selected"), selected);
    if (button.includes(" disabled")) assert.equal(selected, false, "空周期不能选中");
  }
  return buttons.filter((button) => button.includes('aria-pressed="true"'))
    .map((button) => button.match(/data-report-id="([^"]*)"/)[1]);
}

test("日报翻到上月：空日期不选中，末行跨月的已选日期仍选中", (t) => {
  const { html } = renderPanel(t, "day", [report("aug", "2026-08-19"), report("sep", "2026-09-01")], "sep", "2026-08", ["2026-08", "2026-09"]);
  assert.deepEqual(selectedIds(html), ["sep"]);
  assert.match(html, /2026年9月1日，报告可用/);
});

test("日报浏览不包含已选日期的月份时，没有日期选中", (t) => {
  const { html } = renderPanel(t, "day", [report("aug", "2026-08-19"), report("sep", "2026-09-15")], "sep", "2026-08", ["2026-08", "2026-09"]);
  assert.deepEqual(selectedIds(html), []);
});

test("周报浏览其他月份时，空周不选中且有日期说明", (t) => {
  const { html } = renderPanel(t, "week", [report("aug", "2026-08-10", "2026-08-16"), report("sep", "2026-09-14", "2026-09-20")], "sep", "2026-08", ["2026-08", "2026-09"]);
  assert.deepEqual(selectedIds(html), []);
  assert.match(html, /aria-label="第 31 周，2026年7月27日—8月2日，暂无报告"/);
});

test("跨年自然周在次年一月网格中仍显示选中与缺失日期", (t) => {
  const { html } = renderPanel(t, "week", [report("cross", "2025-12-29", "2026-01-04", { missing_days: ["2026-01-02"], period_days: 7, available_days: 6 })], "cross", "2026-01", ["2025-12", "2026-01"]);
  assert.deepEqual(selectedIds(html), ["cross"]);
  assert.match(html, /第 1 周，2025年12月29日—2026年1月4日，数据不完整，6\/7 天可用/);
  assert.match(html, /period-week-day is-missing/);
});

test("月报切到上一年：空月份不选中，并展示状态图例", (t) => {
  const { html } = renderPanel(t, "month", [report("old", "2025-08-01", "2025-08-31"), report("new", "2026-08-01", "2026-08-31")], "new", "2025", ["2025", "2026"]);
  assert.deepEqual(selectedIds(html), []);
  assert.match(html, /aria-label="2025年1月，暂无报告"/);
  assert.match(html, /aria-label="报告状态图例"/);
});

test("月报当前年份只有实际报告被选中，AI 失败标记独立保留", (t) => {
  const { html } = renderPanel(t, "month", [report("aug", "2026-08-01", "2026-08-31", { status: "ai_failed" })], "aug", "2026", ["2026"]);
  assert.deepEqual(selectedIds(html), ["aug"]);
  assert.match(html, /period-status-marker is-ai-failed/);
});

test("失效浏览上下文回落到可用月份，不跳到范围外的已选月份", (t) => {
  const { html, options } = renderPanel(t, "day", [report("sep", "2026-09-01")], "sep", "2026-07", ["2026-08"]);
  assert.equal(options.pickerState.contexts.day, "2026-08");
  assert.match(html, /2026 年 8 月/);
});

test("所选月份无报告时仍保留日期与导航，不能高亮该商品最新报告", (t) => {
  const { html, options } = renderPanel(t, "day", [report("aug", "2026-08-19")], "aug", "2026-09", ["2026-08"], { start_date: "2026-09-03", end_date: "2026-09-03" });
  assert.deepEqual(selectedIds(html), []);
  assert.match(options.container.innerHTML, /2026年9月3日/);
  assert.match(html, /2026 年 9 月/);
  assert.match(html, /data-context-index="0" aria-label="上一个可用周期" >‹/);
});

test("该商品整个粒度无报告时也能打开所选周期日历", (t) => {
  const { html, options } = renderPanel(t, "week", [], "", "2026-08", [], { start_date: "2026-08-24", end_date: "2026-08-30" });
  assert.deepEqual(selectedIds(html), []);
  assert.match(options.container.innerHTML, /2026年8月24日—30日/);
  assert.doesNotMatch(options.container.innerHTML, /id="period-trigger"[^>]*disabled/);
});
