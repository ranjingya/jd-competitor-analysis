import test from "node:test";
import assert from "node:assert/strict";
import { compareValues, sceneValues, formatValue } from "../playground/compact-table-model.js";

test("预览差距按本品减竞品，相对幅度与百分点分别显示", () => {
  assert.deepEqual(compareValues(120, 100, "人"), { primary: "+20", secondary: "+20%", tone: "positive" });
  assert.deepEqual(compareValues(5, 8, "%"), { primary: "-3 pct", secondary: "", tone: "negative" });
  assert.equal(compareValues(0.3, 0.3, "%").primary, "持平");
});

test("空值不能与零混淆，零基数不产生无穷百分比", () => {
  assert.equal(compareValues(20, null, "人").primary, "—");
  assert.equal(compareValues(20, 0, "人").secondary, "基数为 0");
  assert.equal(compareValues(0, 20, "人").secondary, "-100%");
  assert.equal(formatValue(null), "—");
  assert.equal(formatValue(0), "0");
});

test("单竞品隐藏第三列，缺报告保留空槽而不改示例数据", () => {
  const data = [10, 20, 30];
  assert.deepEqual(sceneValues(data, "single"), [10, 20]);
  assert.deepEqual(sceneValues(data, "missing"), [10, 20, null]);
  assert.deepEqual(sceneValues(data, "dual"), data);
  assert.deepEqual(data, [10, 20, 30]);
});
