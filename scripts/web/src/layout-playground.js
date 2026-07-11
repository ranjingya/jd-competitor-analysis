import { renderTrendChart, showTrendState } from "./dashboard.js";
import { loadReport, loadReportIndex } from "./data-client.js";

const layoutDetails = {
  a: {
    badge: "方案 A",
    description: "四项指标在左侧形成纵向导航，右侧趋势图获得最大横向空间。"
  },
  b: {
    badge: "方案 B",
    description: "四项指标以 2×2 矩阵放在左侧，整体高度最低，兼顾扫读和趋势图宽度。"
  },
  c: {
    badge: "方案 C",
    description: "四项指标压成顶部导航带，趋势图铺满整行，横向比较空间最大。"
  }
};

const state = {
  activeMetricId: "gmv",
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
 * 功能说明：渲染当前报告的四项核心指标，并绑定趋势指标切换。
 * 参数 report：当前最新周期的分析结果。
 * 返回值：无；直接更新指标区域并注册点击事件。
 */
function renderMetrics(report) {
  const target = document.querySelector("#playground-metrics");
  const metrics = report.core_metrics || [];
  if (!metrics.some((metric) => metric.id === state.activeMetricId)) {
    state.activeMetricId = metrics[0]?.id || "";
  }
  target.innerHTML = metrics.map((metric) => `
    <button class="playground-metric ${metric.id === state.activeMetricId ? "active" : ""}" type="button" data-metric-id="${escapeHtml(metric.id)}" aria-pressed="${metric.id === state.activeMetricId}">
      <span class="metric-topline">
        <strong>${escapeHtml(metric.label || "-")}</strong>
        <em class="${metric.status === "warning" ? "warning" : "advantage"}">${escapeHtml(formatGap(metric))}</em>
      </span>
      <span class="metric-values">
        <span><b class="self">${escapeHtml(formatValue(metric.self_value, metric.unit))}</b><small>本品</small></span>
        <span><b class="competitor">${escapeHtml(formatValue(metric.competitor_value, metric.unit))}</b><small>竞品</small></span>
      </span>
    </button>
  `).join("");
  target.querySelectorAll("[data-metric-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeMetricId = button.dataset.metricId;
      console.info("Playground 切换趋势指标", state.activeMetricId);
      renderMetrics(report);
      renderTrendChart(state.reports, state.activeMetricId, "day");
    });
  });
}

/**
 * 功能说明：切换 Playground 布局方案并同步说明和按钮状态。
 * 参数 layout：布局方案标识，支持 a、b、c。
 * 返回值：无；直接更新页面布局类名与交互状态。
 */
function switchLayout(layout) {
  const detail = layoutDetails[layout] || layoutDetails.a;
  const stage = document.querySelector("#demo-stage");
  stage.className = `demo-stage layout-${layout}`;
  document.querySelector("#layout-badge").textContent = detail.badge;
  document.querySelector("#layout-description").textContent = detail.description;
  document.querySelectorAll("[data-layout]").forEach((button) => {
    const active = button.dataset.layout === layout;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  console.info("Playground 切换布局", layout);
}

/**
 * 功能说明：读取报告索引和最近日报，初始化指标与趋势布局预览。
 * 返回值：Promise；完成后页面展示三种可切换布局的同一份数据。
 */
async function initialize() {
  console.info("开始初始化布局 Playground");
  try {
    const index = await loadReportIndex();
    const dayEntries = index.reports?.day || [];
    const selectedEntries = dayEntries.slice(-7);
    if (!selectedEntries.length) {
      showTrendState("暂无日报数据");
      return;
    }
    state.reports = await Promise.all(selectedEntries.map((entry) => loadReport(entry)));
    const latestReport = state.reports.at(-1);
    document.querySelector("#data-note").textContent = `${latestReport.meta?.period || "-"} · 使用最近 ${state.reports.length} 个日报动态预览`;
    renderMetrics(latestReport);
    renderTrendChart(state.reports, state.activeMetricId, "day");
    console.info("布局 Playground 初始化完成", { reportCount: state.reports.length });
  } catch (error) {
    console.error("布局 Playground 初始化失败", error);
    document.querySelector("#data-note").textContent = "数据读取失败";
    showTrendState("无法读取当前报告数据", true);
  }
}

document.querySelectorAll("[data-layout]").forEach((button) => {
  button.addEventListener("click", () => switchLayout(button.dataset.layout));
});

initialize();
