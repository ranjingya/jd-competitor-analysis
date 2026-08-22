import assert from "node:assert/strict";
import test from "node:test";

import {
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
