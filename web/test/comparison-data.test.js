import test from "node:test";
import assert from "node:assert/strict";
import { comparisonIndex, comparisonMetrics, comparisonPairs, comparisonTabs, comparisonTrendPoints, sharedValue } from "../src/comparison-data.js";

const metric = (competitor, extra = {}) => ({ id: "gmv", label: "成交金额", self_value: 20, competitor_value: competitor, gap_value: 20 - competitor, ...extra });
const slot = (metrics) => ({ report: { core_metrics: metrics } });

test("本品分组与日历取所有竞品周期的并集，同一天只保留一个入口", () => {
  const index = { pairs: [{ key: "a", selfSpu: "s" }, { key: "b", selfSpu: "s" }, { key: "c", selfSpu: "other" }], reports: { day: [
    { self_spu: "s", competitor_spu: "1", start_date: "2026-09-01", end_date: "2026-09-01", status: "ready" },
    { self_spu: "s", competitor_spu: "2", start_date: "2026-09-01", end_date: "2026-09-01", status: "ai_failed" },
    { self_spu: "s", competitor_spu: "2", start_date: "2026-09-02", end_date: "2026-09-02", status: "ready" }
  ] } };
  index.pairs[0].key = "s::1"; index.pairs[1].key = "s::2";
  const pairs = comparisonPairs(index, "s::1");
  assert.equal(pairs.length, 2);
  const days = comparisonIndex(index, pairs).reports.day;
  assert.equal(days.length, 2);
  assert.equal(days[0].status, "ai_failed");
  assert.equal(days[1].start_date, "2026-09-02");
});

test("核心指标按 ID 对齐，不按各报告数组位置拼接", () => {
  const result = comparisonMetrics([slot([metric(10), metric(2, { id: "visitors" })]), slot([metric(3, { id: "visitors" }), metric(30)])]);
  assert.equal(result[0].self_value, 20);
  assert.deepEqual(result[0].comparisons.map((item) => item.competitor_value), [10, 30]);
});

test("缺失首个报告保留竞品编号，零值仍正常显示", () => {
  const result = comparisonMetrics([{ report: null }, slot([metric(0)])]);
  assert.equal(result[0].comparisons[0], null);
  assert.equal(result[0].comparisons[1].competitor_value, 0);
  assert.equal(result[0].self_value, 20);
});

test("本品不同口径值分开标注，空值不覆盖有效值", () => {
  assert.equal(sharedValue([null, 0]), 0);
  assert.equal(sharedValue([null, undefined]), null);
  assert.match(sharedValue([10, 12], "%"), /对竞品 1：10.00%.*对竞品 2：12.00%/);
});

const columns = [{ key: "keyword", label: "关键词" }, { key: "visitor_gap", label: "访客差距" }, { key: "self_visitors", label: "本品访客" }, { key: "competitor_visitors", label: "竞品访客" }];
const keywordSlot = (rows) => ({ report: { tabs: [{ id: "keywords", columns, rows }] } });
test("优劣势按竞品分组，组内优势在前且不修改报告", () => {
  const first = keywordSlot([]);
  const second = keywordSlot([]);
  first.report.tabs[0].highlights = [{ label: "一的劣势", status: "warning" }, { label: "一的优势", status: "advantage" }];
  second.report.tabs[0].highlights = [{ label: "二的优势", status: "advantage" }, { label: "二的劣势", status: "warning" }];
  const [tab] = comparisonTabs([first, second]);
  assert.deepEqual(tab.highlightGroups.map((group) => [group.competitorLabel, ...group.highlights.map((item) => item.label)]), [
    ["竞品 1", "一的优势", "一的劣势"], ["竞品 2", "二的优势", "二的劣势"],
  ]);
  assert.equal(first.report.tabs[0].highlights[0].label, "一的劣势");
});

test("优劣势空槽保留编号，单竞品仅一组", () => {
  const second = keywordSlot([]);
  second.report.tabs[0].highlights = [{ label: "二的优势", status: "advantage" }];
  const [tab] = comparisonTabs([{ report: null }, second]);
  assert.deepEqual(tab.highlightGroups[0], { competitorLabel: "竞品 1", highlights: [] });
  assert.equal(tab.highlightGroups[1].competitorLabel, "竞品 2");
  assert.equal(tab.highlightGroups[1].highlights[0].label, "二的优势");
  assert.equal(comparisonTabs([second])[0].highlightGroups.length, 1);
});

test("关键词全量外连接，独有行保留，缺失竞品列不复制另一侧", () => {
  const [tab] = comparisonTabs([
    keywordSlot([{ keyword: "相同", self_visitors: 10, competitor_visitors: 2, visitor_gap: 8 }, { keyword: "独有1", self_visitors: 0, competitor_visitors: 4 }]),
    keywordSlot([{ keyword: "独有2", self_visitors: 5, competitor_visitors: 1 }, { keyword: "相同", self_visitors: 10, competitor_visitors: 20, visitor_gap: -10 }])
  ]);
  assert.equal(tab.rows.length, 3);
  const row = tab.rows.find((item) => item.keyword === "相同");
  assert.equal(row.c0_visitor_gap, 8);
  assert.equal(row.c1_visitor_gap, -10);
  assert.equal(tab.rows.find((item) => item.keyword === "独有1").c1_competitor_visitors, null);
  assert.equal(tab.measures[0].columns.length, 6);
  assert.deepEqual(tab.measures[0].columns.map((column) => column.key), ["keyword", "c0_visitor_gap", "c1_visitor_gap", "self_visitors", "c0_competitor_visitors", "c1_competitor_visitors"]);
  assert.deepEqual(tab.columns.map((column) => column.key), ["keyword", "c0_visitor_gap", "c1_visitor_gap", "self_visitors", "c0_competitor_visitors", "c1_competitor_visitors"]);
});

test("客户画像按维度与名称组合匹配，同名不同维度不合并", () => {
  const report = (rows) => ({ report: { tabs: [{ id: "customer_profile", dimension_field: "dimension", columns: [{ key: "name", label: "画像项" }, { key: "self_rate", label: "本品占比", unit: "%" }, { key: "competitor_rate", label: "竞品占比", unit: "%" }], rows }] } });
  const [tab] = comparisonTabs([report([{ dimension: "省份", name: "其他", self_rate: 1 }]), report([{ dimension: "城市", name: "其他", self_rate: 2 }])]);
  assert.equal(tab.rows.length, 2);
});

test("渠道按完整层级匹配，末级同名不混淆，单竞品不产生额外列", () => {
  const [tab] = comparisonTabs([{ report: { tabs: [{ id: "traffic", columns: [{ ...columns[0], key: "path" }, ...columns.slice(1)], rows: [
    { level_1: "站内", level_2: "其他", path: "站内 > 其他" }, { level_1: "站外", level_2: "其他", path: "站外 > 其他" }
  ] }] } }]);
  assert.equal(tab.rows.length, 2);
  assert.equal(tab.columns.some((column) => column.key.startsWith("c1_")), false);
});

test("趋势三方按日期对齐，任一竞品缺失只中断该竞品", () => {
  const report = (date, value) => ({ meta: { period_start: date }, core_metrics: [metric(value)] });
  const points = comparisonTrendPoints([[report("2026-09-01", 0)], [report("2026-09-02", 9)]], "gmv", "day", { startDate: "2026-09-01", endDate: "2026-09-03" });
  assert.deepEqual(points.map((point) => point.competitorValues), [[0, null], [null, 9], [null, null]]);
  assert.deepEqual(points.map((point) => point.missing), [false, false, true]);
  assert.equal(points[1].selfValue, 20);
});

test("周月趋势按周期起点对齐，不依赖响应顺序", () => {
  const report = (date, value) => ({ meta: { period_start: date }, core_metrics: [metric(value)] });
  const points = comparisonTrendPoints([[report("2026-08-01", 2)], [report("2026-07-01", 3), report("2026-08-01", 4)]], "gmv", "month", {});
  assert.deepEqual(points.map((point) => point.competitorValues), [[null, 3], [2, 4]]);
});
