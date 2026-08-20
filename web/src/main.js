import { renderDashboard, renderTrendChart, showPageState, showTrendState } from "./dashboard.js";
import { loadReport, loadReportIndex } from "./data-client.js";
import { closePeriodPicker, renderPeriodPicker } from "./period-picker.js";
import {
  defaultPairKey,
  indexForPair,
  reportPairs,
  reportsForPair
} from "./report-selection.js";
import { bindSkuDialog, closeSkuDialog } from "./sku-dialog.js";

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

function reportsFor(granularity) {
  return reportsForPair(state.index, granularity, state.activePairKey);
}

function pairLabel(pair) {
  const selfLabel = pair.selfName
    ? `${pair.selfName}（${pair.selfSpu}）`
    : `本品 ${pair.selfSpu}`;
  const competitorLabel = pair.competitorName
    ? `${pair.competitorName}（${pair.competitorSpu}）`
    : `竞品 ${pair.competitorSpu}`;
  return `${selfLabel} vs ${competitorLabel}`;
}

/**
 * 功能说明：渲染商品对原生选择框，并在切换后选择该商品对的最新报告。
 * 参数：无；读取当前报告索引和 activePairKey。
 * 返回值：无；直接更新商品对选择框并绑定 change 事件。
 */
function renderPairSelector() {
  const select = document.querySelector("#pair-select");
  const pairs = reportPairs(state.index);
  select.replaceChildren(...pairs.map((pair) => {
    const option = document.createElement("option");
    option.value = pair.key;
    option.textContent = pairLabel(pair);
    option.title = option.textContent;
    return option;
  }));
  select.value = state.activePairKey;
  select.disabled = pairs.length <= 1;
  select.onchange = () => {
    state.activePairKey = select.value;
    selectReportsForActivePair();
    selectActiveReport();
  };
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

/**
 * 功能说明：按当前粒度和所选周期筛选趋势报告，日报围绕选中日期双向补齐至 7 条。
 * 参数 entry：当前周期的报告索引条目。
 * 返回值：按日期升序排列的趋势报告条目数组。
 */
function trendEntriesFor(entry) {
  const reports = [...reportsFor(state.activeGranularity)].sort((left, right) =>
    String(left.start_date || "").localeCompare(String(right.start_date || ""))
  );
  if (state.activeGranularity === "day") {
    const selectedIndex = Math.max(0, reports.findIndex((item) => item.report_id === entry.report_id));
    const windowSize = 7;
    const centeredStart = selectedIndex - Math.floor(windowSize / 2);
    const start = Math.min(Math.max(0, centeredStart), Math.max(0, reports.length - windowSize));
    return reports.slice(start, start + windowSize);
  }
  if (state.activeGranularity === "week") {
    const selectedMonth = String(entry.start_date || "").slice(0, 7);
    return reports.filter((item) => String(item.start_date || "").startsWith(selectedMonth));
  }
  return reports;
}

/**
 * 功能说明：加载当前指标所需的多个周期报告并刷新趋势图。
 * 参数 entry：当前周期的报告索引条目。
 * 返回值：Promise；完成后趋势图更新为最新请求。
 */
async function renderActiveTrend(entry) {
  const requestId = state.trendRequestId + 1;
  state.trendRequestId = requestId;
  const entries = trendEntriesFor(entry);
  showTrendState("正在加载趋势数据");
  try {
    const reports = await Promise.all(entries.map((item) => loadReport(item)));
    if (requestId !== state.trendRequestId) {
      return;
    }
    renderTrendChart(reports, state.activeMetricId, state.activeGranularity, entry.start_date);
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
    state.index = await loadReportIndex();
    state.activePairKey = defaultPairKey(state.index);
    selectReportsForActivePair();
    document.querySelector("#updated-at").textContent = state.index.updated_at
      ? `数据生成于 ${state.index.updated_at.slice(0, 19).replace("T", " ")}`
      : "暂无分析结果";
    renderControls();
    bindPeriodPickerDismissal();
    bindSkuDialog(
      document.querySelector("#sku-trigger"),
      document.querySelector("#sku-dialog"),
      () => state.currentEntry
    );
    await selectActiveReport();
  } catch (error) {
    console.error("报告索引加载失败", error);
    document.querySelector("#updated-at").textContent = "索引读取失败";
    showPageState("无法读取报告索引，请先运行批量分析脚本", true);
  }
}

initialize();
