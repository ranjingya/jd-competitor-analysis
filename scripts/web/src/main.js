import { renderDashboard, renderTrendChart, showPageState, showTrendState } from "./dashboard.js";
import { loadReport, loadReportIndex } from "./data-client.js";
import { closePeriodPicker, renderPeriodPicker } from "./period-picker.js";

const granularityLabels = {
  day: "日",
  week: "周",
  month: "月"
};

const state = {
  index: null,
  activeGranularity: "day",
  activeMetricId: "gmv",
  currentEntry: null,
  selectedPeriods: {},
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
  return state.index?.reports?.[granularity] || [];
}

function renderControls() {
  const reports = reportsFor(state.activeGranularity);
  const latest = reports.at(-1);
  const selectedKey = state.selectedPeriods[state.activeGranularity] || latest?.period_key || "";
  renderPeriodPicker({
    container: document.querySelector("#period-picker"),
    index: state.index,
    activeGranularity: state.activeGranularity,
    selectedPeriods: { ...state.selectedPeriods, [state.activeGranularity]: selectedKey },
    pickerState: periodPickerState,
    onPeriodChange(granularity, periodKey) {
      state.activeGranularity = granularity;
      state.selectedPeriods[granularity] = periodKey;
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
    String(left.period_start || "").localeCompare(String(right.period_start || ""))
  );
  if (state.activeGranularity === "day") {
    const selectedIndex = Math.max(0, reports.findIndex((item) => item.period_key === entry.period_key));
    const windowSize = 7;
    const centeredStart = selectedIndex - Math.floor(windowSize / 2);
    const start = Math.min(Math.max(0, centeredStart), Math.max(0, reports.length - windowSize));
    return reports.slice(start, start + windowSize);
  }
  if (state.activeGranularity === "week") {
    const selectedMonth = String(entry.period_start || "").slice(0, 7);
    return reports.filter((item) => String(item.period_start || "").startsWith(selectedMonth));
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
    renderTrendChart(reports, state.activeMetricId, state.activeGranularity, entry.period_start);
  } catch (error) {
    console.error("趋势数据加载失败", error);
    if (requestId === state.trendRequestId) {
      showTrendState("趋势数据加载失败，请检查对应周期报告", true);
    }
  }
}

async function selectActiveReport() {
  const reports = reportsFor(state.activeGranularity);
  if (!reports.length) {
    renderControls();
    showPageState("当前粒度暂无可用报告");
    showTrendState("当前粒度暂无趋势数据");
    return;
  }
  const selectedKey = state.selectedPeriods[state.activeGranularity] || reports.at(-1).period_key;
  const entry = reports.find((item) => item.period_key === selectedKey) || reports.at(-1);
  state.currentEntry = entry;
  state.selectedPeriods[state.activeGranularity] = entry.period_key;
  renderControls();
  showPageState(`正在加载${entry.period}报告`);
  try {
    const report = await loadReport(entry);
    if (!(report.core_metrics || []).some((item) => item.id === state.activeMetricId)) {
      state.activeMetricId = report.core_metrics?.[0]?.id || "";
    }
    renderDashboard(report, state.activeMetricId);
    await renderActiveTrend(entry);
  } catch (error) {
    console.error("报告加载失败", error);
    showPageState("报告加载失败，请检查分析结果是否完整", true);
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
    state.activeGranularity = reportsFor("day").length
      ? "day"
      : Object.keys(granularityLabels).find((key) => reportsFor(key).length) || "day";
    for (const granularity of Object.keys(granularityLabels)) {
      const latest = reportsFor(granularity).at(-1);
      if (latest) {
        state.selectedPeriods[granularity] = latest.period_key;
      }
    }
    document.querySelector("#updated-at").textContent = state.index.updated_at
      ? `数据生成于 ${state.index.updated_at.slice(0, 19).replace("T", " ")}`
      : "暂无分析结果";
    renderControls();
    bindPeriodPickerDismissal();
    await selectActiveReport();
  } catch (error) {
    console.error("报告索引加载失败", error);
    document.querySelector("#updated-at").textContent = "索引读取失败";
    showPageState("无法读取报告索引，请先运行批量分析脚本", true);
  }
}

initialize();
