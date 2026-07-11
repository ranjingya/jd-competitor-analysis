import { renderTrendChart, showTrendState } from "./dashboard.js";
import { loadReport, loadReportIndex } from "./data-client.js";

const effectDetails = {
  a: { badge: "方案 A", description: "使用低对比深色描边和轻阴影，不增加额外符号。" },
  b: { badge: "方案 B", description: "在卡片右侧增加小箭头，直接指向当前联动的趋势图。" },
  c: { badge: "方案 C", description: "用底部居中的短线标识当前项，视觉最轻。" },
  d: { badge: "方案 D", description: "只加强卡片原有的棕色或绿色，完全不引入第三种强调色。" },
  e: { badge: "方案 E", description: "通过轻微上浮和投影建立层级，保留卡片原有边界。" }
};

const state = {
  activeEffect: "a",
  activeMetricId: "gmv",
  latestReport: null,
  reports: []
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatValue(value, unit = "") {
  if (typeof value !== "number") {
    return "-";
  }
  const text = Number.isInteger(value)
    ? value.toLocaleString("zh-CN")
    : value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${text}${unit}`;
}

function formatGap(metric) {
  if (metric.gap_abs_text == null || metric.gap_abs_text === "") {
    return "-";
  }
  const value = String(metric.gap_abs_text).replace(/^[+-]/, "");
  const sign = metric.status === "warning" ? "-" : "+";
  const unit = metric.id === "conversion_rate" ? "pct" : "";
  const ratio = String(metric.ratio_text || "").match(/(\d+(?:\.\d+)?)x/i)?.[1];
  return `${sign}${value}${unit}${ratio ? ` · ${ratio}x` : ""}`;
}

/**
 * 功能说明：渲染当前报告的核心指标，并绑定趋势指标切换。
 * 参数 report：当前最新日报的分析结果。
 * 返回值：无；直接更新指标区域和点击事件。
 */
function renderMetrics(report) {
  const target = document.querySelector("#playground-metrics");
  const metrics = report.core_metrics || [];
  if (!metrics.some((metric) => metric.id === state.activeMetricId)) {
    state.activeMetricId = metrics[0]?.id || "";
  }
  target.innerHTML = metrics.map((metric) => {
    const statusClass = metric.status === "warning" ? "warning" : "advantage";
    return `
      <button class="metric-card status-${statusClass} ${metric.id === state.activeMetricId ? "active" : ""}" type="button" data-metric-id="${escapeHtml(metric.id)}" aria-pressed="${metric.id === state.activeMetricId}">
        <span class="metric-topline">
          <strong>${escapeHtml(metric.label || "-")}</strong>
          <em>${escapeHtml(formatGap(metric))}</em>
        </span>
        <span class="metric-values">
          <span><b class="self">${escapeHtml(formatValue(metric.self_value, metric.unit))}</b><small>本品真实值</small></span>
          <span><b class="competitor">${escapeHtml(formatValue(metric.competitor_value, metric.unit))}</b><small>竞品估算值</small></span>
        </span>
      </button>
    `;
  }).join("");
  target.querySelectorAll("[data-metric-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeMetricId = button.dataset.metricId;
      console.info("选中效果 Playground 切换趋势指标", state.activeMetricId);
      renderMetrics(report);
      renderTrendChart(state.reports, state.activeMetricId, "day");
    });
  });
}

/**
 * 功能说明：切换选中效果方案并同步说明和按钮状态。
 * 参数 effect：选中效果标识，支持 a、b、c、d、e。
 * 返回值：无；直接更新页面方案类名与交互状态。
 */
function switchEffect(effect) {
  const detail = effectDetails[effect] || effectDetails.a;
  state.activeEffect = effectDetails[effect] ? effect : "a";
  document.querySelector("#demo-stage").className = `demo-stage effect-${state.activeEffect}`;
  document.querySelector("#effect-badge").textContent = detail.badge;
  document.querySelector("#effect-description").textContent = detail.description;
  document.querySelectorAll("[data-effect]").forEach((button) => {
    const active = button.dataset.effect === state.activeEffect;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  console.info("选中效果 Playground 切换方案", state.activeEffect);
}

/**
 * 功能说明：读取报告索引和最近日报，初始化选中效果预览。
 * 返回值：Promise；完成后展示五种可切换效果和真实趋势数据。
 */
async function initialize() {
  console.info("开始初始化选中效果 Playground");
  try {
    const index = await loadReportIndex();
    const selectedEntries = (index.reports?.day || []).slice(-7);
    if (!selectedEntries.length) {
      showTrendState("暂无日报数据");
      return;
    }
    state.reports = await Promise.all(selectedEntries.map((entry) => loadReport(entry)));
    state.latestReport = state.reports.at(-1);
    document.querySelector("#data-note").textContent = `${state.latestReport.meta?.period || "-"} · 使用最近 ${state.reports.length} 个日报动态预览`;
    renderMetrics(state.latestReport);
    renderTrendChart(state.reports, state.activeMetricId, "day");
    console.info("选中效果 Playground 初始化完成", { reportCount: state.reports.length });
  } catch (error) {
    console.error("选中效果 Playground 初始化失败", error);
    document.querySelector("#data-note").textContent = "数据读取失败";
    showTrendState("无法读取当前报告数据", true);
  }
}

document.querySelectorAll("[data-effect]").forEach((button) => {
  button.addEventListener("click", () => switchEffect(button.dataset.effect));
});

initialize();
