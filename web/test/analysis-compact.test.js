import test from "node:test";
import assert from "node:assert/strict";
import { compactColumnGroups, compactColumns, compactDifference, compactJudgement, compactSortField, compactSortRows } from "../src/analysis-compact.js";
import { comparisonTabs } from "../src/comparison-data.js";
import { sortFlatTreeRowsBySiblings } from "../src/analysis-sort.js";

const sourceColumns = [
  { key: "path", label: "渠道" }, { key: "self_visitors", label: "本品访客" },
  { key: "competitor_visitors", label: "竞品访客" }, { key: "visitor_gap", label: "访客差距" },
  { key: "judgement", label: "判断" },
  { key: "self_rate", label: "本品占比", unit: "%" }, { key: "competitor_rate", label: "竞品占比", unit: "%" },
];
const slot = (rows) => ({ report: { tabs: [{ id: "traffic", columns: sourceColumns, rows }] } });
const fixture = () => comparisonTabs([
  slot([{ path: "搜索", self_visitors: 10, competitor_visitors: 20, visitor_gap: -10, self_rate: 30, competitor_rate: 40, judgement: "本品落后" }]),
  slot([{ path: "搜索", self_visitors: 10, competitor_visitors: 5, visitor_gap: 5, self_rate: 30, competitor_rate: 20, judgement: "本品领先" }]),
])[0];

test("本品与差距合并为指标列，身份单列，竞品原值后置且本品不重复", () => {
  const tab = fixture();
  const columns = compactColumns(tab.columns, 2);
  assert.deepEqual(columns.map((column) => column.key), ["path", "compact_roles", "compact_judgement", "self_visitors", "self_rate",
    "c0_competitor_visitors", "c0_competitor_rate", "c1_competitor_visitors", "c1_competitor_rate"]);
  assert.equal(columns.filter((column) => column.key === "self_visitors").length, 1);
  assert.equal(columns.find((column) => column.key === "self_visitors").label, "访客");
  assert.ok(columns.filter((column) => column.kind === "raw").every((column) => !column.key.includes("self_")));
});

test("优先展示已有差值，百分比以对应竞品为基数，占比只用百分点", () => {
  const tab = fixture();
  const columns = compactColumns(tab.columns, 2);
  const visitors = columns.find((column) => column.key === "self_visitors");
  assert.deepEqual(compactDifference(tab.rows[0], visitors, 0), { value: -10, unit: "", percent: -50, zeroBase: false });
  assert.equal(compactDifference(tab.rows[0], visitors, 1).percent, 100);
  assert.equal(compactDifference({ ...tab.rows[0], c0_visitor_gap: -9 }, visitors, 0).value, -9);
  assert.deepEqual(compactDifference(tab.rows[0], columns.find((column) => column.key === "self_rate"), 0), { value: -10, unit: "pct", percent: null, zeroBase: false });
});

test("缺失商品对保持空槽，不用另一份本品值补差距；零值不丢失", () => {
  const [tab] = comparisonTabs([{ report: null }, slot([{ path: "搜索", self_visitors: 0, competitor_visitors: 0 }])]);
  const column = compactColumns(tab.columns, 2).find((item) => item.key === "self_visitors");
  assert.deepEqual(compactColumnGroups(compactColumns(tab.columns, 2)).map((item) => item.label), ["渠道", "对比", "差距", "竞品 1", "竞品 2"]);
  assert.equal(compactDifference(tab.rows[0], column, 0).value, null);
  assert.equal(compactDifference(tab.rows[0], column, 1).value, 0);
  assert.equal(compactDifference({ ...tab.rows[0], c1_self_visitors: 5 }, column, 1).zeroBase, true);
});

test("不同本品口径各自计算差距，合并展示值不参与运算", () => {
  const [tab] = comparisonTabs([slot([{ path: "搜索", self_visitors: 10, competitor_visitors: 5 }]), slot([{ path: "搜索", self_visitors: 20, competitor_visitors: 8 }])]);
  const column = compactColumns(tab.columns, 2).find((item) => item.key === "self_visitors");
  assert.match(tab.rows[0].self_visitors, /对竞品/);
  assert.equal(compactDifference(tab.rows[0], column, 0).value, 5);
  assert.equal(compactDifference(tab.rows[0], column, 1).value, 12);
});

test("单竞品与单指标筛选只展示对应原值，不产生多余判断或指标", () => {
  const [tab] = comparisonTabs([slot([{ path: "搜索", self_visitors: 1, competitor_visitors: 2 }])]);
  const columns = compactColumns(tab.measures.find((item) => item.key === "self_visitors").columns, 1);
  assert.deepEqual(columns.map((column) => column.key), ["path", "compact_roles", "self_visitors", "c0_competitor_visitors"]);
  assert.equal(columns[2].count, 1);
  assert.deepEqual(compactColumnGroups(columns).map((column) => column.label), ["渠道", "对比", "差距", "竞品 1"]);
});

test("二层表头按差距和竞品分组，具体指标不重复商品前缀且字段稳定", () => {
  const columns = compactColumns(fixture().columns, 2);
  const groups = compactColumnGroups(columns);
  assert.deepEqual(groups.map((column) => column.label), ["渠道", "对比", "差距", "竞品 1", "竞品 2"]);
  assert.equal(groups[2].derived, true);
  assert.equal(groups[2].children[0].key, "compact_judgement");
  assert.deepEqual(groups[3].children.map((column) => column.label), ["访客", "占比"]);
  assert.deepEqual(groups.flatMap((group) => group.children || [group]).map((column) => column.key), columns.map((column) => column.key));
});

test("判断文案省略本品前缀，其他状态和缺失值保持原样", () => {
  assert.equal(compactJudgement("本品领先"), "领先");
  assert.equal(compactJudgement("本品落后"), "落后");
  assert.equal(compactJudgement("基本持平"), "基本持平");
  assert.equal(compactJudgement("无完整口径"), "无完整口径");
  assert.equal(compactJudgement(null), null);
});

test("排序可按指定竞品差值且保持父子层级，空差距沉底", () => {
  const tab = fixture();
  const columns = compactColumns(tab.columns, 2);
  const data = [
    { ...tab.rows[0], id: "parent", parent_id: null },
    { ...tab.rows[0], id: "low", parent_id: "parent", c1_visitor_gap: -8 },
    { ...tab.rows[0], id: "high", parent_id: "parent", c1_visitor_gap: 8 },
    { ...tab.rows[0], id: "missing", parent_id: "parent", c1_competitor_visitors: null },
  ];
  const sorted = sortFlatTreeRowsBySiblings(compactSortRows(data, columns, "1"), [{ field: compactSortField(columns, "self_visitors"), order: "desc" }]);
  assert.deepEqual(sorted.map((row) => row.id), ["parent", "high", "low", "missing"]);
  assert.equal(data[0].sort_self_visitors, undefined);
  assert.equal(compactSortField(columns, "c0_competitor_visitors"), "c0_competitor_visitors");
});
