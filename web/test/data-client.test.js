import assert from "node:assert/strict";
import test from "node:test";

import {
  loadProductPairs,
  loadReport,
  loadReportPeriods,
  loadReportSkus,
  loadReportTrends
} from "../src/data-client.js";


test("商品对列表使用独立轻量接口", async () => {
  const originalFetch = globalThis.fetch;
  const requestedUrls = [];
  globalThis.fetch = async (url) => {
    requestedUrls.push(url);
    return { ok: true, async json() { return { items: [] }; } };
  };

  try {
    const result = await loadProductPairs();
    assert.deepEqual(result.items, []);
    assert.deepEqual(requestedUrls, ["/api/product-pairs"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
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

test("周期和趋势接口只携带当前查询范围", async () => {
  const originalFetch = globalThis.fetch;
  const requestedUrls = [];
  globalThis.fetch = async (url) => {
    requestedUrls.push(url);
    return {
      ok: true,
      async json() {
        return { items: [] };
      }
    };
  };
  const pair = { selfSpu: "10001", competitorSpu: "20001" };

  try {
    await loadReportPeriods(pair, "day", "2026-08");
    await loadReportTrends(pair, "day", "2026-08-11", "2026-08-17");

    assert.equal(requestedUrls.length, 2);
    assert.match(requestedUrls[0], /^\/api\/reports\/periods\?/);
    assert.match(requestedUrls[0], /context=2026-08/);
    assert.match(requestedUrls[1], /^\/api\/reports\/trends\?/);
    assert.match(requestedUrls[1], /start_date=2026-08-11/);
    assert.match(requestedUrls[1], /end_date=2026-08-17/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
