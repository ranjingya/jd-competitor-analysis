import test from "node:test";
import assert from "node:assert/strict";
import { summarize } from "../playground/overall-summary.js";

const metrics = ["amount", "visitors", "conversion"].map((key) => ({ key, label: key }));
const self = { metrics: { amount: 20, visitors: 30, conversion: 8 } };

test("总体结论分别比较两个竞品，按比较方向归组", () => {
  const competitors = [
    { available: true, metrics: { amount: 10, visitors: 20, conversion: 9 } },
    { available: true, metrics: { amount: 40, visitors: 50, conversion: 7 } },
  ];
  const result = summarize({ self, competitors, metrics });
  assert.equal(result.groups.length, 2);
  assert.deepEqual(result.groups[0].labels, ["amount", "visitors"]);
  assert.deepEqual(result.rows.map((row) => row.comparisons.map((item) => item.direction)), [[1, -1], [1, -1], [-1, 1]]);
});

test("无报告或无指标不作为零值参与结论", () => {
  const competitors = [
    { available: true, metrics: { amount: 0, visitors: null } },
    { available: false, metrics: { amount: 10, visitors: 10, conversion: 10 } },
  ];
  const result = summarize({ self, competitors, metrics });
  assert.deepEqual(result.rows.map((row) => row.comparisons.map((item) => item.direction)), [[1, null], [null, null], [null, null]]);
});

test("单竞品及持平保留各自方向", () => {
  const result = summarize({ self, competitors: [{ available: true, metrics: self.metrics }], metrics });
  assert.equal(result.groups.length, 1);
  assert.deepEqual(result.groups[0].comparisons.map((item) => item.direction), [0]);
});
