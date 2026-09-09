import { renderDashboard, renderTrendChart, showPageState, showTrendState } from "./dashboard.js";
import {
  loadProductPairs,
  loadReport,
  loadReportPeriods,
  loadReportTrends
} from "./data-client.js";
import { closePairPicker, renderPairPicker } from "./pair-picker.js";
import { closePeriodPicker, renderPeriodPicker } from "./period-picker.js";
import {
  defaultPairKey,
  findReportForPeriod,
  indexFromProductPairs,
  mergePeriodEntries,
  reportPair,
  reportPairs
} from "./report-selection.js";
import { bindSkuDialog, closeSkuDialog } from "./sku-dialog.js";
import { comparisonIndex, comparisonPairs } from "./comparison-data.js";
import { formatBeijingDateTime } from "./time-format.js";

const granularityLabels = {
  day: "日",
  week: "周",
  month: "月"
};

const state = {
  index: null,
  activePairKey: "",
  activeGranularity: "day",
  activeMetricId: "gmv",
  currentEntry: null,
  selectedReportIds: {},
  selectedPeriods: {},
  periodContexts: {},
  loadedPeriodContexts: new Set(),
  loadingPeriodContexts: new Map(),
  reportRequestId: 0,
  trendRequestId: 0
};

const periodPickerState = {
  open: false,
  closing: false,
  animateOpen: false,
  contexts: {},
  draftGranularity: null
};

const pairPickerState = {
  open: false
};

function reportsFor(granularity) {
  return comparisonIndex(state.index, comparisonPairs(state.index, state.activePairKey)).reports[granularity];
}

function activePair() {
  return reportPair(state.index, state.activePairKey);
}

function contextForEntry(granularity, entry) {
  if (!entry) return "";
  return granularity === "month"
    ? String(entry.start_date || "").slice(0, 4)
    : String(entry.start_date || "").slice(0, 7);
}

/**
 * 功能说明：按需加载指定商品对年月内的可用报告，并合并到页面导航状态。
 * 参数 granularity：day、week 或 month。
 * 参数 context：日报/周报月份 YYYY-MM，或月报年份 YYYY。
 * 参数 pair：待查询商品对，默认使用当前本品的导航商品对。
 * 返回值：Promise；周期元数据加载并渲染完成后结束。
 */
async function ensurePeriodContext(granularity, context, pair = activePair()) {
  if (!pair || !context) return;
  const pairKey = pair.key;
  const requestKey = `${pairKey}:${granularity}:${context}`;
  if (state.loadedPeriodContexts.has(requestKey)) return true;
  if (state.loadingPeriodContexts.has(requestKey)) {
    return state.loadingPeriodContexts.get(requestKey);
  }
  const request = loadReportPeriods(pair, granularity, context)
    .then((result) => {
      mergePeriodEntries(state.index, granularity, pairKey, context, result.items);
      state.periodContexts[pairKey] ||= { day: [], week: [], month: [] };
      state.periodContexts[pairKey][granularity] = result.contexts || [];
      state.loadedPeriodContexts.add(requestKey);
      if (state.activePairKey === pairKey) {
        renderControls();
      }
      return true;
    })
    .catch((error) => {
      console.error("可用报告周期加载失败", error);
      return false;
    })
    .finally(() => {
      state.loadingPeriodContexts.delete(requestKey);
    });
  state.loadingPeriodContexts.set(requestKey, request);
  return request;
}

/**
 * 功能说明：渲染本品分组选择器，切换商品时保留已选粒度和日期范围。
 * 参数：无；读取当前报告索引和 activePairKey。
 * 返回值：无；直接更新商品对下拉框并绑定切换事件。
 */
function renderPairSelector() {
  const pairs = reportPairs(state.index);
  renderPairPicker({
    container: document.querySelector("#pair-picker"),
    pairs,
    activePairKey: state.activePairKey,
    pickerState: pairPickerState,
    onBeforeOpen() {
      closePeriodPicker(document.querySelector("#period-picker"), periodPickerState);
    },
    onPairChange(pairKey) {
      closePairPicker(document.querySelector("#pair-picker"), pairPickerState, true);
      if (pairKey === state.activePairKey) {
        return;
      }
      state.activePairKey = pairKey;
      // 已选周期独立于报告存在性；仅为从未选择过的粒度补默认周期。
      selectReportsForActivePair(true);
      periodPickerState.open = false;
      periodPickerState.closing = false;
      periodPickerState.contexts = {};
      selectActiveReport();
    }
  });
}

/**
 * 功能说明：为当前商品对选择默认粒度和各粒度最新报告。
 * 参数 preservePeriod：是否保留各粒度已选周期，切换商品时为 true。
 * 返回值：无。
 */
function selectReportsForActivePair(preservePeriod = false) {
  const availableGranularity = Object.keys(granularityLabels)
    .find((granularity) => reportsFor(granularity).length);
  if (!preservePeriod && !reportsFor(state.activeGranularity).length) {
    state.activeGranularity = availableGranularity || "day";
  }
  for (const granularity of Object.keys(granularityLabels)) {
    const latest = reportsFor(granularity).at(-1);
    if (preservePeriod && state.selectedPeriods[granularity]) continue;
    if (latest) {
      state.selectedReportIds[granularity] = latest.report_id;
      state.selectedPeriods[granularity] = { start_date: latest.start_date, end_date: latest.end_date };
    } else {
      delete state.selectedReportIds[granularity];
    }
  }
}

function renderControls() {
  renderPairSelector();
  const pairs = comparisonPairs(state.index, state.activePairKey);
  const periodContexts = Object.fromEntries(Object.keys(granularityLabels).map((grain) => [grain,
    [...new Set(pairs.flatMap((pair) => state.periodContexts[pair.key]?.[grain] || []))].sort()
  ]));
  const reportCounts = Object.fromEntries(Object.keys(granularityLabels).map((grain) => [grain,
    pairs.reduce((total, pair) => total + (pair.reportCounts?.[grain] || 0), 0)
  ]));
  renderPeriodPicker({
    container: document.querySelector("#period-picker"),
    index: comparisonIndex(state.index, pairs),
    activeGranularity: state.activeGranularity,
    selectedReportIds: state.selectedReportIds,
    selectedPeriods: state.selectedPeriods,
    pickerState: periodPickerState,
    periodContexts,
    reportCounts,
    onContextChange(granularity, context) {
      Promise.all(pairs.map((pair) => ensurePeriodContext(granularity, context, pair)))
        .then(() => { if (activePair()?.selfSpu === pairs[0]?.selfSpu) renderControls(); });
    },
    onReportChange(granularity, reportId) {
      state.activeGranularity = granularity;
      state.selectedReportIds[granularity] = reportId;
      const entry = reportsFor(granularity).find((item) => item.report_id === reportId);
      state.selectedPeriods[granularity] = { start_date: entry.start_date, end_date: entry.end_date };
      selectActiveReport();
    }
  });
}

function bindPeriodPickerDismissal() {
  document.addEventListener("click", (event) => {
    const container = document.querySelector("#period-picker");
    const eventPath = typeof event.composedPath === "function" ? event.composedPath() : [];
    if (!periodPickerState.open || !container || container.contains(event.target) || eventPath.includes(container)) return;
    closePeriodPicker(container, periodPickerState);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !periodPickerState.open) return;
    closePeriodPicker(document.querySelector("#period-picker"), periodPickerState);
    document.querySelector("#period-trigger")?.focus();
  });
}

function bindPairPickerDismissal() {
  document.addEventListener("click", (event) => {
    const container = document.querySelector("#pair-picker");
    const eventPath = typeof event.composedPath === "function" ? event.composedPath() : [];
    if (!pairPickerState.open || !container || container.contains(event.target) || eventPath.includes(container)) {
      return;
    }
    closePairPicker(container, pairPickerState);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !pairPickerState.open) {
      return;
    }
    closePairPicker(document.querySelector("#pair-picker"), pairPickerState, true);
  });
}

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

/**
 * 功能说明：计算当前周期趋势图需要查询的自然日期范围。
 * 参数 entry：当前选中的轻量报告条目。
 * 返回值：包含 startDate 和 endDate 的查询范围。
 */
function trendRangeFor(entry) {
  const startDate = new Date(`${entry.start_date}T00:00:00Z`);
  if (state.activeGranularity === "day") {
    startDate.setUTCDate(startDate.getUTCDate() - 6);
    return { startDate: isoDate(startDate), endDate: entry.start_date };
  }
  if (state.activeGranularity === "week") {
    const year = startDate.getUTCFullYear();
    const month = startDate.getUTCMonth();
    return {
      startDate: isoDate(new Date(Date.UTC(year, month, 1))),
      endDate: isoDate(new Date(Date.UTC(year, month + 1, 0)))
    };
  }
  const year = startDate.getUTCFullYear();
  return { startDate: `${year}-01-01`, endDate: `${year}-12-31` };
}

/**
 * 功能说明：并行加载当前本品各竞品的轻量趋势，独立展示失败与空值。
 * 参数 entry：当前周期的报告索引条目。
 * 返回值：Promise；完成后趋势图更新为最新请求。
 */
async function renderActiveTrend(entry) {
  const requestId = state.trendRequestId + 1;
  state.trendRequestId = requestId;
  const pair = activePair();
  if (!pair) {
    showTrendState("当前商品对不存在", true);
    return;
  }
  const range = trendRangeFor(entry);
  showTrendState("正在加载趋势数据");
  try {
    const pairs = comparisonPairs(state.index, state.activePairKey);
    const results = await Promise.allSettled(pairs.map((item) => loadReportTrends(
      item,
      state.activeGranularity,
      range.startDate,
      range.endDate
    )));
    if (requestId !== state.trendRequestId) {
      return;
    }
    renderTrendChart(
      results.map((result) => result.status === "fulfilled" ? result.value.items || [] : []),
      state.activeMetricId,
      state.activeGranularity,
      entry.start_date,
      range,
      results.map((result) => result.status === "rejected")
    );
  } catch (error) {
    console.error("趋势数据加载失败", error);
    if (requestId === state.trendRequestId) {
      showTrendState("趋势数据加载失败，请检查对应周期报告", true);
    }
  }
}

/**
 * 功能说明：按当前本品和所选周期并行加载竞品报告，隔离过期响应和单侧失败。
 * 参数：无，从页面 state 读取本品、粒度和起止日期。
 * 返回值：Promise<void>，页面更新完成后结束。
 */
async function selectActiveReport() {
  const requestId = state.reportRequestId + 1;
  state.reportRequestId = requestId;
  state.trendRequestId += 1;
  state.currentEntry = null;
  closeSkuDialog(document.querySelector("#sku-dialog"));
  document.querySelector("#sku-trigger").disabled = true;
  const granularity = state.activeGranularity;
  const pairKey = state.activePairKey;
  const period = state.selectedPeriods[granularity];
  renderControls();
  const periodLabel = period ? (period.start_date === period.end_date ? period.start_date : `${period.start_date}—${period.end_date}`) : "";
  document.querySelector("#meta").textContent = `${periodLabel} · 分析粒度：${granularityLabels[granularity]}`;
  document.querySelector("#updated-at").textContent = "正在读取所选报告";
  showPageState("正在读取所选周期报告");
  const pairs = comparisonPairs(state.index, pairKey);
  const slots = await Promise.all(pairs.map(async (pair) => {
    let entry = findReportForPeriod(state.index, granularity, pair.key, period);
    if (!entry && period) {
      const loaded = await ensurePeriodContext(granularity, contextForEntry(granularity, period), pair);
      if (!loaded) return { pair, entry: null, report: null, error: true };
      entry = findReportForPeriod(state.index, granularity, pair.key, period);
    }
    if (!entry) return { pair, entry: null, report: null };
    try { return { pair, entry, report: await loadReport(entry) }; }
    catch (error) {
      console.error("竞品报告加载失败", pair.key, error);
      return { pair, entry, report: null, error: true };
    }
  }));
  if (requestId !== state.reportRequestId) return;
  const available = slots.filter((slot) => slot.report);
  const entry = available[0]?.entry;
  if (!entry) {
    state.selectedReportIds[granularity] = "";
    renderControls();
    const failed = slots.some((slot) => slot.error);
    document.querySelector("#updated-at").textContent = failed ? "报告读取失败" : "所选周期暂无报告";
    showPageState(failed ? "所选周期读取失败，请重新选择以重试" : `${periodLabel} 当前本品暂无报告，请选择其他周期`, failed);
    showTrendState("所选周期暂无趋势数据");
    return;
  }
  state.currentEntry = entry;
  state.selectedReportIds[state.activeGranularity] = entry.report_id;
  renderControls();
  showPageState(`正在加载${entry.period}报告`);
  try {
    const report = available[0].report;
    document.querySelector("#sku-trigger").disabled = false;
    const updatedAt = formatBeijingDateTime(available.map((slot) => slot.entry.updated_at).filter(Boolean).sort().at(-1) || state.index.updated_at);
    document.querySelector("#updated-at").textContent = updatedAt ? `数据生成于 ${updatedAt}` : "报告已加载";
    if (!(report.core_metrics || []).some((item) => item.id === state.activeMetricId)) {
      state.activeMetricId = report.core_metrics?.[0]?.id || "";
    }
    renderDashboard(slots, state.activeMetricId);
    await renderActiveTrend(entry);
  } catch (error) {
    console.error("报告加载失败", error);
    if (requestId === state.reportRequestId) {
      state.currentEntry = null;
      document.querySelector("#updated-at").textContent = "报告读取失败";
      showPageState("报告加载失败，请检查分析结果是否完整", true);
    }
  }
}

document.addEventListener("dashboard:metric-select", (event) => {
  state.activeMetricId = event.detail?.metricId || state.activeMetricId;
  if (state.currentEntry) {
    renderActiveTrend(state.currentEntry);
  }
});

async function initialize() {
  try {
    state.index = indexFromProductPairs(await loadProductPairs());
    state.activePairKey = defaultPairKey(state.index);
    selectReportsForActivePair();
    const updatedAt = formatBeijingDateTime(state.index.updated_at);
    document.querySelector("#updated-at").textContent = updatedAt
      ? `数据生成于 ${updatedAt}`
      : "暂无分析结果";
    renderControls();
    bindPeriodPickerDismissal();
    bindPairPickerDismissal();
    bindSkuDialog(
      document.querySelector("#sku-trigger"),
      document.querySelector("#sku-dialog"),
      () => state.currentEntry
    );
    await selectActiveReport();
  } catch (error) {
    console.error("商品对列表加载失败", error);
    document.querySelector("#updated-at").textContent = "商品对读取失败";
    showPageState("无法读取商品对，请先运行批量分析脚本", true);
  }
}

initialize();
