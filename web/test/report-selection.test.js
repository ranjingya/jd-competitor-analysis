import assert from "node:assert/strict";
import test from "node:test";

import {
  groupProductPairs,
  findReportForPeriod,
  defaultPairKey,
  indexFromProductPairs,
  indexForPair,
  mergePeriodEntries,
  reportPairKey,
  reportPairs,
  reportsForPair
} from "../src/report-selection.js";


const index = {
  reports: {
    day: [
      {
        report_id: "report-a-old",
        self_spu: "10001",
        competitor_spu: "20001",
        self_name: "本品一",
        competitor_name: "竞品一",
        self_image_url: "https://example.com/self-a.jpg",
        competitor_image_url: "https://example.com/competitor-a.jpg"
      },
      {
        report_id: "report-b-new",
        self_spu: "10002",
        competitor_spu: "20002",
        self_name: "本品二",
        competitor_name: "竞品二"
      }
    ],
    week: [
      {
        report_id: "report-a-week",
        self_spu: "10001",
        competitor_spu: "20001"
      }
    ],
    month: []
  }
};

test("本品分组支持任意竞品数，同一竞品可属于不同本品", () => {
  const pairs = [
    { key: "a::x", selfSpu: "a", competitorSpu: "x", selfName: "本品甲" },
    { key: "a::y", selfSpu: "a", competitorSpu: "y", selfImageUrl: "https://example.com/a.jpg" },
    { key: "a::z", selfSpu: "a", competitorSpu: "z" },
    { key: "b::x", selfSpu: "b", competitorSpu: "x" },
  ];
  const groups = groupProductPairs([...pairs, pairs[0]]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].competitors.map((pair) => pair.key), ["a::x", "a::y", "a::z"]);
  assert.equal(groups[0].imageUrl, "https://example.com/a.jpg");
  assert.equal(groups[1].competitors[0].key, "b::x");
  assert.deepEqual(groupProductPairs([]), []);
});

test("日周月精确匹配商品对和范围，缺失周期不回退到其他报告", () => {
  for (const granularity of ["day", "week", "month"]) {
    const period = { start_date: "2026-08-01", end_date: "2026-08-01" };
    const matching = { ...period, self_spu: "a", competitor_spu: "x", report_id: "match" };
    const entries = { reports: { [granularity]: [matching, { ...matching, competitor_spu: "y", end_date: "2026-08-31", report_id: "other" }] } };
    assert.equal(findReportForPeriod(entries, granularity, "a::x", period), matching);
    assert.equal(findReportForPeriod(entries, granularity, "a::y", period), null);
    assert.equal(findReportForPeriod(entries, granularity, "a::x", { ...period, start_date: "2026-09-01" }), null);
  }
});

test("商品对从三个粒度去重，并默认选择最新日报所属商品对", () => {
  const pairs = reportPairs(index);

  assert.deepEqual(pairs.map((pair) => pair.key), ["10001::20001", "10002::20002"]);
  assert.equal(pairs[0].selfName, "本品一");
  assert.equal(pairs[0].selfImageUrl, "https://example.com/self-a.jpg");
  assert.equal(pairs[0].competitorImageUrl, "https://example.com/competitor-a.jpg");
  assert.equal(defaultPairKey(index), "10002::20002");
});

test("周期索引仅保留当前商品对报告", () => {
  const pairKey = reportPairKey(index.reports.day[0]);
  const filtered = indexForPair(index, pairKey);

  assert.equal(reportsForPair(index, "day", pairKey).length, 1);
  assert.equal(filtered.reports.day[0].report_id, "report-a-old");
  assert.equal(filtered.reports.week[0].report_id, "report-a-week");
  assert.deepEqual(filtered.reports.month, []);
});

test("商品对接口只初始化各粒度最新报告，并可合并按月周期", () => {
  const latest = indexFromProductPairs({
    updated_at: "2026-08-18T01:00:00Z",
    items: [
      {
        self_spu: "10001",
        competitor_spu: "20001",
        self_name: "本品一",
        competitor_name: "竞品一",
        report_counts: { day: 2, week: 0, month: 0 },
        latest_reports: {
          day: {
            report_id: "report-new",
            self_spu: "10001",
            competitor_spu: "20001",
            start_date: "2026-08-18",
            end_date: "2026-08-18"
          },
          week: null,
          month: null
        }
      }
    ]
  });

  assert.equal(latest.reports.day.length, 1);
  assert.equal(latest.pairs[0].reportCounts.day, 2);
  mergePeriodEntries(latest, "day", "10001::20001", "2026-08", [
    {
      report_id: "report-old",
      self_spu: "10001",
      competitor_spu: "20001",
      start_date: "2026-08-17",
      end_date: "2026-08-17"
    },
    latest.reports.day[0]
  ]);
  assert.deepEqual(
    latest.reports.day.map((entry) => entry.report_id),
    ["report-old", "report-new"]
  );
});
