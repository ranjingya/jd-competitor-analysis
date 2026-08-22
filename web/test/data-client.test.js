import assert from "node:assert/strict";
import test from "node:test";

import { loadReport, loadReportSkus, normalizeReportIndex } from "../src/data-client.js";


test("报告索引按 start_date 和 end_date 由旧到新排列", () => {
  const index = normalizeReportIndex({
    reports: {
      day: [
        {
          report_id: "report-new",
          start_date: "2026-08-18",
          end_date: "2026-08-18",
          updated_at: "2026-08-19T01:00:00Z"
        },
        {
          report_id: "report-old",
          start_date: "2026-08-17",
          end_date: "2026-08-17",
          updated_at: "2026-08-18T01:00:00Z"
        }
      ]
    }
  });

  assert.deepEqual(index.reports.day.map((entry) => entry.report_id), [
    "report-old",
    "report-new"
  ]);
  assert.deepEqual(index.reports.week, []);
  assert.deepEqual(index.reports.month, []);
});

test("相同周期的不同报告使用 report_id 独立缓存", async () => {
  const originalFetch = globalThis.fetch;
  const requestedUrls = [];
  globalThis.fetch = async (url) => {
    requestedUrls.push(url);
    return {
      ok: true,
      async json() {
        return { path: url };
      }
    };
  };

  try {
    const first = await loadReport({
      report_id: "cache-report-a",
      period_key: "day:2026-08-17",
      path: "/api/reports/cache-report-a"
    });
    const second = await loadReport({
      report_id: "cache-report-b",
      period_key: "day:2026-08-17",
      path: "/api/reports/cache-report-b"
    });
    const repeatedFirst = await loadReport({
      report_id: "cache-report-a",
      period_key: "day:2026-08-17",
      path: "/api/reports/cache-report-a"
    });

    assert.equal(first.path, "/api/reports/cache-report-a");
    assert.equal(second.path, "/api/reports/cache-report-b");
    assert.equal(repeatedFirst, first);
    assert.deepEqual(requestedUrls, [
      "/api/reports/cache-report-a",
      "/api/reports/cache-report-b"
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("SKU 构成按 report_id 请求并缓存", async () => {
  const originalFetch = globalThis.fetch;
  const requestedUrls = [];
  globalThis.fetch = async (url) => {
    requestedUrls.push(url);
    return {
      ok: true,
      async json() {
        return { report_id: "sku-report", sku_count: 18, items: [] };
      }
    };
  };

  try {
    const entry = { report_id: "sku-report" };
    const first = await loadReportSkus(entry);
    const second = await loadReportSkus(entry);

    assert.equal(first.sku_count, 18);
    assert.equal(second, first);
    assert.deepEqual(requestedUrls, ["/api/reports/sku-report/skus"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
