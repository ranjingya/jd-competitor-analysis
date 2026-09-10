import test from "node:test";
import assert from "node:assert/strict";
import { headerHelpText } from "../src/table-header-help.js";

test("只解释访客与两种渠道占比，不解释差距", () => {
  assert.match(headerHelpText({ suffix: "visitors" }), /区间中位值/);
  assert.match(headerHelpText({ key: "c1_competitor_visitors" }), /区间中位值/);
  assert.match(headerHelpText({ suffix: "current_level_visitor_rate_pct" }), /直接子渠道/);
  assert.match(headerHelpText({ key: "self_total_visitor_rate_pct" }), /不使用顶部 SKU/);
  for (const key of ["visitor_gap", "gmv", "judgement", "conversion_rate_pct"]) {
    assert.equal(headerHelpText({ key }), null);
  }
});
