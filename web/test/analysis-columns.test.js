import test from "node:test";
import assert from "node:assert/strict";
import { isDerivedColumn, orderAnalysisColumns } from "../src/analysis-columns.js";

test("名称列固定在首位，蓝色计算列稳定前置，原始值列随后", () => {
  const columns = [
    { key: "path", label: "渠道路径" },
    { key: "self_visitors", label: "本品访客" },
    { key: "self_current_level_visitor_rate_pct", label: "本品同层访客占比" },
    { key: "c0_competitor_visitors", label: "竞品 1 · 访客" },
    { key: "c0_judgement", label: "竞品 1 · 判断" },
    { key: "c1_visitor_gap", label: "竞品 2 · 访客差距" }
  ];
  const original = [...columns];
  assert.deepEqual(orderAnalysisColumns(columns).map((column) => column.key), ["path", "self_current_level_visitor_rate_pct", "c0_judgement", "c1_visitor_gap", "self_visitors", "c0_competitor_visitors"]);
  assert.deepEqual(columns, original);
});

test("占比列按既有蓝色表头规则判断，画像原始占比不算计算列", () => {
  assert.equal(isDerivedColumn({ key: "self_rate", label: "本品占比" }), false);
  assert.equal(isDerivedColumn({ key: "c1_gap_rate", label: "竞品 2 · 占比差距" }), true);
  assert.equal(isDerivedColumn({ key: "c1_competitor_visitor_share_pct", label: "竞品 2 · 访客占比" }), true);
  assert.deepEqual(orderAnalysisColumns([]), []);
});
