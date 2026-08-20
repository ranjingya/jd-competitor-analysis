import assert from "node:assert/strict";
import test from "node:test";

import {
  defaultPairKey,
  indexForPair,
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
