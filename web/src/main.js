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
  indexFromProductPairs,
  indexForPair,
  mergePeriodEntries,
  reportPair,
  reportPairs,
  reportsForPair
} from "./report-selection.js";
import { bindSkuDialog, closeSkuDialog } from "./sku-dialog.js";
import { bindHeroSummaryDialog } from "./hero-summary.js";

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
  open: false,
  closing: false,
  animateOpen: false
};

function reportsFor(granularity) {
  return reportsForPair(state.index, granularity, state.activePairKey);
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
 * 功能说明：按需加载当前商品对指定年月的可用报告，并合并到页面导航状态。
 * 参数 granularity：day、week 或 month。
 * 参数 context：日报/周报月份 YYYY-MM，或月报年份 YYYY。
 * 返回值：Promise；周期元数据加载并渲染完成后结束。
 */
async function ensurePeriodContext(granularity, context) {
  const pair = activePair();
  if (!pair || !context) return;
  const pairKey = pair.key;
  const requestKey = `${pairKey}:${granularity}:${context}`;
  if (state.loadedPeriodContexts.has(requestKey)) return;
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
    })
    .catch((error) => {
      console.error("可用报告周期加载失败", error);
    })
    .finally(() => {
      state.loadingPeriodContexts.delete(requestKey);
    });
  state.loadingPeriodContexts.set(requestKey, request);
  return request;
}

/**
 * 功能说明：渲染带商品图的商品对选择器，并在切换后选择该商品对的最新报告。
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
      selectReportsForActivePair();
      selectActiveReport();
    }
  });
}

/**
 * 功能说明：为当前商品对选择默认粒度和各粒度最新报告。
 * 参数：无；读取 activePairKey 并更新选中报告状态。
 * 返回值：无。
 */
function selectReportsForActivePair() {
  const availableGranularity = Object.keys(granularityLabels)
    .find((granularity) => reportsFor(granularity).length);
  if (!reportsFor(state.activeGranularity).length) {
    state.activeGranularity = availableGranularity || "day";
  }
  for (const granularity of Object.keys(granularityLabels)) {
    const latest = reportsFor(granularity).at(-1);
    if (latest) {
      state.selectedReportIds[granularity] = latest.report_id;
    } else {
      delete state.selectedReportIds[granularity];
    }
  }
}

function renderControls() {
  renderPairSelector();
  const pair = activePair();
  const reports = reportsFor(state.activeGranularity);
  const latest = reports.at(-1);
  const selectedReportId = state.selectedReportIds[state.activeGranularity]
    || latest?.report_id
    || "";
  renderPeriodPicker({
    container: document.querySelector("#period-picker"),
    index: indexForPair(state.index, state.activePairKey),
    activeGranularity: state.activeGranularity,
    selectedReportIds: {
      ...state.selectedReportIds,
      [state.activeGranularity]: selectedReportId
    },
    pickerState: periodPickerState,
    periodContexts: state.periodContexts[state.activePairKey] || {},
    reportCounts: pair?.reportCounts || {},
    onContextChange(granularity, context) {
      ensurePeriodContext(granularity, context);
    },
    onReportChange(granularity, reportId) {
      state.activeGranularity = granularity;
      state.selectedReportIds[granularity] = reportId;
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
 * 功能说明：加载当前指标所需的多个周期报告并刷新趋势图。
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
    const result = await loadReportTrends(
      pair,
      state.activeGranularity,
      range.startDate,
      range.endDate
    );
    if (requestId !== state.trendRequestId) {
      return;
    }
    renderTrendChart(
      result.items || [],
      state.activeMetricId,
      state.activeGranularity,
      entry.start_date,
      range
    );
  } catch (error) {
    console.error("趋势数据加载失败", error);
    if (requestId === state.trendRequestId) {
      showTrendState("趋势数据加载失败，请检查对应周期报告", true);
    }
  }
}

async function selectActiveReport() {
  const requestId = state.reportRequestId + 1;
  state.reportRequestId = requestId;
  closeSkuDialog(document.querySelector("#sku-dialog"));
  document.querySelector("#sku-trigger").disabled = true;
  const reports = reportsFor(state.activeGranularity);
  if (!reports.length) {
    renderControls();
    showPageState("当前粒度暂无可用报告");
    showTrendState("当前粒度暂无趋势数据");
    return;
  }
  const selectedReportId = state.selectedReportIds[state.activeGranularity]
    || reports.at(-1).report_id;
  const entry = reports.find((item) => item.report_id === selectedReportId) || reports.at(-1);
  state.currentEntry = entry;
  state.selectedReportIds[state.activeGranularity] = entry.report_id;
  document.querySelector("#sku-trigger").disabled = false;
  renderControls();
  showPageState(`正在加载${entry.period}报告`);
  try {
    const report = await loadReport(entry);
    if (requestId !== state.reportRequestId) return;
    if (!(report.core_metrics || []).some((item) => item.id === state.activeMetricId)) {
      state.activeMetricId = report.core_metrics?.[0]?.id || "";
    }
    renderDashboard(report, state.activeMetricId);
    await renderActiveTrend(entry);
  } catch (error) {
    console.error("报告加载失败", error);
    if (requestId === state.reportRequestId) {
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
    document.querySelector("#updated-at").textContent = state.index.updated_at
      ? `数据生成于 ${state.index.updated_at.slice(0, 19).replace("T", " ")}`
      : "暂无分析结果";
    renderControls();
    bindPeriodPickerDismissal();
    bindPairPickerDismissal();
    bindSkuDialog(
      document.querySelector("#sku-trigger"),
      document.querySelector("#sku-dialog"),
      () => state.currentEntry
    );
    bindHeroSummaryDialog(
      document.querySelector("#summary-dialog"),
      document.querySelector("#hero-summary-trigger")
    );
    await selectActiveReport();
  } catch (error) {
    console.error("商品对列表加载失败", error);
    document.querySelector("#updated-at").textContent = "商品对读取失败";
    showPageState("无法读取商品对，请先运行批量分析脚本", true);
  }
}

initialize();
