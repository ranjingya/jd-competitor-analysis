import assert from "node:assert/strict";
import test from "node:test";

import { buildMissingTrendSeries, buildTrendPoints } from "../src/trend-data.js";


function report(date, selfValue, competitorValue) {
  return {
    meta: {
      period: date,
      period_start: date,
      granularity: "day"
    },
    core_metrics: [
      {
        id: "gmv",
        label: "成交金额",
        self_value: selfValue,
        competitor_value: competitorValue
      }
    ]
  };
}


test("日报趋势为缺失日期保留断点和背景带", () => {
  const points = buildTrendPoints(
    [report("2026-08-17", 1200, 900), report("2026-08-19", 1500, 1100)],
    "gmv",
    "day",
    { startDate: "2026-08-17", endDate: "2026-08-19" }
  );
  const series = buildMissingTrendSeries(points);

  assert.deepEqual(points.map((item) => item.missing), [false, true, false]);
  assert.equal(points[1].selfValue, null);
  assert.deepEqual(series.data, [[1, 1]]);
  assert.equal(series.silent, true);
});


test("连续缺失日期合并为一个无数据区域", () => {
  const points = buildTrendPoints(
    [report("2026-08-16", 1200, 900), report("2026-08-21", 1500, 1100)],
    "gmv",
    "day",
    { startDate: "2026-08-16", endDate: "2026-08-21" }
  );

  assert.deepEqual(buildMissingTrendSeries(points).data, [[1, 4]]);
});


test("完整趋势不添加无数据背景系列", () => {
  const points = buildTrendPoints(
    [report("2026-08-17", 1200, 900), report("2026-08-18", 1300, 950)],
    "gmv",
    "day",
    { startDate: "2026-08-17", endDate: "2026-08-18" }
  );

  assert.equal(buildMissingTrendSeries(points), null);
});
