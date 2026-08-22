import assert from "node:assert/strict";
import test from "node:test";

import { compactHeroSummary, detailPoints, hasDetailPoints } from "../src/hero-summary.js";


test("核心指标生成可完整展示的优点和弱点短摘要", () => {
  const metrics = [
    { label: "成交金额", status: "advantage" },
    { label: "访客数", status: "advantage" },
    { label: "成交转化率", status: "warning" },
    { label: "成交客单价", status: "advantage" }
  ];

  assert.equal(compactHeroSummary(metrics, "advantage"), "成交金额、访客数、成交客单价领先");
  assert.equal(compactHeroSummary(metrics, "warning"), "成交转化率落后");
});

test("没有匹配指标时返回稳定短摘要", () => {
  assert.equal(compactHeroSummary([], "advantage"), "暂无明显优势");
  assert.equal(compactHeroSummary([], "warning"), "暂无明显短板");
});

test("新旧详情结构都转换为逐条展示内容", () => {
  assert.deepEqual(detailPoints(["访客规模领先。", "客单价更高。"]), ["访客规模领先。", "客单价更高。"]);
  assert.deepEqual(detailPoints("访客规模领先。客单价更高。"), ["访客规模领先。", "客单价更高。"]);
  assert.deepEqual(
    detailPoints(["访客规模领先；客单价更高。", "成交金额领先。转化率仍有差距。"]),
    ["访客规模领先；", "客单价更高。", "成交金额领先。", "转化率仍有差距。"]
  );
});

test("空详情不应被识别为结构化 AI 摘要", () => {
  assert.equal(hasDetailPoints([]), false);
  assert.equal(hasDetailPoints(["", "  "]), false);
  assert.equal(hasDetailPoints(""), false);
  assert.equal(hasDetailPoints(["访客规模领先。"]), true);
});
