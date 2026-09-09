import * as echarts from "echarts/core";
import { CustomChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import { mountAnalysisVxeTable, unmountAnalysisVxeTable } from "./analysis-vxe-table.js";
import { bindHeroSummaryDialog, compactHeroSummary, hasDetailPoints } from "./hero-summary.js";
import { buildMissingTrendSeries } from "./trend-data.js";
import { comparisonMetrics, comparisonTabs, comparisonTrendPoints } from "./comparison-data.js";
import "./comparison-dashboard.css";

echarts.use([CustomChart, LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer]);

const dashboardState = {
  data: null,
  activeTab: 0,
  activeMetricId: "",
  dimensions: {},
  measures: {},
  sorts: {}
};

let trendChartInstance = null;
let trendResizeObserver = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}


function formatValue(value, unit = "") {
  if (value == null || value === "" || value === "-") {
    return "-";
  }
  if (typeof value === "number") {
    return `${value.toFixed(2)}${unit}`;
  }
  return `${value}${String(value).startsWith("对竞品 ") ? "" : unit}`;
}

/**
 * 功能说明：格式化只在负数前保留减号的展示值。
 * 参数 value：待格式化数值。
 * 参数 unit：数值后的展示单位。
 * 返回值：固定两位小数的展示文本，正数不带加号。
 */
function formatSignedValue(value, unit = "") {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "-";
  }
  const normalized = Math.abs(value) < 0.005 ? 0 : value;
  return `${normalized.toFixed(2)}${unit}`;
}

/**
 * 功能说明：展示重点卡差值对应的指标名称和带方向数值。
 * 参数 item：包含指标名、本品值、竞品值和差值模式的重点数据。
 * 返回值：明确指标名称的差值、独有状态或数据不足标识。
 */
function formatHighlightGap(item) {
  const metricLabel = item.metric_label || "指标";
  const hasSelfValue = typeof item.self_value === "number";
  const hasCompetitorValue = typeof item.competitor_value === "number";
  if (!hasSelfValue || !hasCompetitorValue) {
    if (hasSelfValue) {
      return `${metricLabel} 本品独有`;
    }
    if (hasCompetitorValue) {
      return `${metricLabel} 竞品独有`;
    }
    return `${metricLabel} -`;
  }
  const gap = typeof item.gap_value === "number"
    ? item.gap_value
    : item.self_value - item.competitor_value;
  const unit = item.gap_mode === "percentage_point" ? "pct" : (item.unit || "");
  return `${metricLabel} ${formatSignedValue(gap, unit)}`;
}

/**
 * 功能说明：展示重点卡相对竞品的差距幅度。
 * 参数 item：包含本品值、竞品值和差距幅度的重点数据。
 * 返回值：百分比幅度文本；百分点模式不重复展示。
 */
function formatHighlightAmplitude(item) {
  if (item.gap_mode === "percentage_point") {
    return "";
  }
  const fallbackRate = (
    typeof item.self_value === "number"
    && typeof item.competitor_value === "number"
    && item.competitor_value !== 0
  )
    ? (item.self_value - item.competitor_value) / item.competitor_value * 100
    : null;
  const rate = typeof item.gap_rate_pct === "number" ? item.gap_rate_pct : fallbackRate;
  return typeof rate === "number" ? formatSignedValue(rate, "%") : "";
}

/**
 * 功能说明：展示核心指标的带方向差值。
 * 参数 item：核心指标卡数据。
 * 返回值：包含差值名称和单位的展示文本。
 */
function formatMetricGap(item) {
  const fallbackGap = (
    typeof item.self_value === "number"
    && typeof item.competitor_value === "number"
  )
    ? item.self_value - item.competitor_value
    : null;
  const value = typeof item.gap_value === "number" ? item.gap_value : fallbackGap;
  const unit = item.id === "conversion_rate" ? "pct" : "";
  return formatSignedValue(value, unit);
}

/**
 * 功能说明：展示核心指标相对竞品的差距幅度。
 * 参数 item：包含本品值、竞品值和差距幅度的核心指标卡。
 * 返回值：百分比幅度文本；成交转化率不重复展示。
 */
function formatMetricAmplitude(item) {
  if (item.id === "conversion_rate" || item.gap_mode === "percentage_point") {
    return "";
  }
  const fallbackRate = (
    typeof item.self_value === "number"
    && typeof item.competitor_value === "number"
    && item.competitor_value !== 0
  )
    ? (item.self_value - item.competitor_value) / item.competitor_value * 100
    : null;
  const rate = typeof item.gap_rate_pct === "number" ? item.gap_rate_pct : fallbackRate;
  return typeof rate === "number" ? formatSignedValue(rate, "%") : "";
}

/**
 * 功能说明：渲染当前差距维度的摘要、筛选项和 VXE-Table 数据表格。
 * 参数：无；读取 dashboardState 中的当前报告和选中状态。
 * 返回值：无；直接更新 Tab 导航与内容区域。
 */
function renderTabs() {
  const previousPageScroll = { left: window.scrollX, top: window.scrollY };
  unmountAnalysisVxeTable();
  const tabs = dashboardState.data?.tabs || [];
  if (dashboardState.activeTab >= tabs.length) {
    dashboardState.activeTab = 0;
  }
  const nav = document.querySelector("#tabs");
  nav.innerHTML = tabs.map((tab, index) => `
    <button class="tab ${index === dashboardState.activeTab ? "active" : ""}" type="button" data-tab-index="${index}">
      ${escapeHtml(tab.label || `Tab ${index + 1}`)}
    </button>
  `).join("");
  nav.querySelectorAll("[data-tab-index]").forEach((button) => {
    button.addEventListener("click", () => {
      dashboardState.activeTab = Number(button.dataset.tabIndex);
      renderTabs();
    });
  });

  const current = tabs[dashboardState.activeTab] || tabs[0] || {};
  const highlightGroups = current.highlightGroups || [];
  const rows = current.rows || [];
  const measureKey = dashboardState.measures[current.id] || "all";
  const columns = current.measures?.find((item) => item.key === measureKey)?.columns || current.columns || [];
  const currentSort = dashboardState.sorts[current.id] || null;
  const dimensionField = current.dimension_field;
  const dimensionOptions = dimensionField
    ? [...new Set(rows.map((row) => row[dimensionField]).filter(Boolean))]
    : [];
  const activeDimension = dashboardState.dimensions[current.id] || dimensionOptions[0] || "";
  const dimensionRows = activeDimension
    ? rows.filter((row) => row[dimensionField] === activeDimension)
    : rows;

  document.querySelector("#tab-body").innerHTML = `
    <section class="tab-section">
      <div class="comparison-insight-groups">
        ${highlightGroups.map((group) => `
        <section class="comparison-insight-group" aria-label="${escapeHtml(group.competitorLabel)}优劣势">
          <h3 class="section-title">${escapeHtml(group.competitorLabel)} 优劣势</h3>
          <div class="insight-grid">
        ${group.highlights.map((item) => {
          const amplitudeText = formatHighlightAmplitude(item);
          return `
          <article class="insight-card ${item.status === "warning" ? "warning" : "advantage"}">
            <div class="insight-card-label">
              <p class="insight-type">${item.status === "warning" ? "劣势" : "优势"}</p>
              <h4>${escapeHtml(item.label || "-")}</h4>
            </div>
            <div class="insight-compare ${item.status === "warning" ? "warning" : "advantage"}">
              <span>${escapeHtml(formatHighlightGap(item))}</span>
              ${amplitudeText ? `
                <span class="insight-compare-divider" aria-hidden="true"></span>
                <span>${escapeHtml(amplitudeText)}</span>
              ` : ""}
            </div>
          </article>
        `;
        }).join("") || '<p class="empty-inline">当前周期暂无重点数据</p>'}
          </div>
        </section>`).join("") || '<p class="empty-inline">当前周期暂无重点数据</p>'}
      </div>
    </section>
    <section class="tab-section">
      <div class="comparison-table-controls">
        <span>对比指标</span>
        <div class="comparison-measures" role="group" aria-label="对比指标">
          ${[{ key: "all", label: "全部" }, ...(current.measures || [])].map((item) => `<button type="button" class="dimension-tab ${item.key === measureKey ? "active" : ""}" data-measure="${escapeHtml(item.key)}" aria-pressed="${item.key === measureKey}">${escapeHtml(item.label)}</button>`).join("")}
        </div>
      </div>
      ${dimensionOptions.length ? `
        <div class="dimension-tabs">
          ${dimensionOptions.map((dimension) => `
            <button class="dimension-tab ${dimension === activeDimension ? "active" : ""}" type="button" data-dimension="${escapeHtml(dimension)}">
              ${escapeHtml(dimension)}
            </button>
          `).join("")}
        </div>
      ` : ""}
      <div id="analysis-vxe-mount"></div>
    </section>
  `;

  const tableTarget = document.querySelector("#analysis-vxe-mount");
  document.querySelectorAll("[data-measure]").forEach((button) => {
    button.onclick = () => {
      const key = button.dataset.measure;
      const scrollLeft = button.parentElement.scrollLeft;
      dashboardState.measures[current.id] = key;
      delete dashboardState.sorts[current.id];
      renderTabs();
      document.querySelector(".comparison-measures").scrollLeft = scrollLeft;
      [...document.querySelectorAll("[data-measure]")].find((item) => item.dataset.measure === key)?.focus({ preventScroll: true });
    };
  });
  if (tableTarget) {
    mountAnalysisVxeTable(tableTarget, {
      id: current.id,
      competitorCount: highlightGroups.length,
      columns,
      rows: dimensionRows,
      sortState: currentSort,
      onSortChange(sortState) {
        if (sortState) {
          dashboardState.sorts[current.id] = sortState;
        } else {
          delete dashboardState.sorts[current.id];
        }
      }
    });
  }
  window.scrollTo(previousPageScroll.left, previousPageScroll.top);

  document.querySelectorAll("[data-dimension]").forEach((button) => {
    button.addEventListener("click", () => {
      dashboardState.dimensions[current.id] = button.dataset.dimension;
      renderTabs();
    });
  });
}

function renderAiRecommendations() {
  const target = document.querySelector("#ai-recommendations");
  target.innerHTML = dashboardState.slots.map((slot, index) => `<section class="comparison-advice"><h3>竞品 ${index + 1}</h3><div class="ai-recommendations-list">${recommendationsHtml(slot)}</div></section>`).join("");
}

function recommendationsHtml(slot) {
  if (!slot.report) return `<p class="empty-inline">${slot.error ? "报告读取失败" : "所选周期暂无报告"}</p>`;
  const reportStatus = slot.report.report_status;
  if (reportStatus === "ai_failed" || reportStatus === "pending_ai") {
    const failed = reportStatus === "ai_failed";
    return `
      <div class="ai-report-state ${failed ? "is-error" : "is-pending"}">
        <strong>${failed ? "AI 劣势建议生成失败" : "AI 劣势建议生成中"}</strong>
      </div>`;
  }
  const suggestions = (slot.report.ai_recommendations || [])
    .filter((item) => item.status === "warning")
    .slice(0, 5);
  return suggestions.map((item) => {
    const actions = item.actions || [];
    return `
      <section class="ai-recommendation-card warning">
        <p class="ai-recommendation-type">${escapeHtml(item.source_label || "AI 劣势建议")} · ${escapeHtml(item.target || "-")}</p>
        <p class="ai-recommendation-primary-action">${escapeHtml(actions[0] || "查看完整分析后确定动作")}</p>
        <details class="ai-recommendation-details">
          <summary>查看依据与验收</summary>
          ${actions.length > 1 ? `
            <ul class="ai-recommendation-secondary-actions">
              ${actions.slice(1).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}
            </ul>
          ` : ""}
          <p><span>依据</span>${escapeHtml(item.evidence || "-")}</p>
          <p><span>验收</span>${escapeHtml(item.validation || "-")}</p>
        </details>
      </section>
    `;
  }).join("") || '<p class="empty-inline">当前报告暂无可展示的 AI 劣势建议。</p>';
}

function compactNumber(value) {
  const absolute = Math.abs(value);
  if (absolute >= 1000000) {
    return `${(value / 1000000).toFixed(2)}M`;
  }
  if (absolute >= 1000) {
    return `${(value / 1000).toFixed(2)}K`;
  }
  return value.toFixed(2);
}

function disposeTrendChart() {
  trendResizeObserver?.disconnect();
  trendResizeObserver = null;
  if (trendChartInstance && !trendChartInstance.isDisposed()) {
    trendChartInstance.dispose();
  }
  trendChartInstance = null;
}

/**
 * 功能说明：显示趋势图加载、空数据或错误状态。
 * 参数 message：需要显示的状态文本。
 * 参数 isError：是否使用错误提示语义。
 * 返回值：无；直接更新趋势图容器。
 */
export function showTrendState(message, isError = false) {
  disposeTrendChart();
  const target = document.querySelector("#trend-chart");
  target.innerHTML = `<div class="trend-empty ${isError ? "error" : ""}">${escapeHtml(message)}</div>`;
}

/**
 * 功能说明：使用多个周期的分析结果绘制本品和竞品趋势折线图。
 * 参数 reports：按竞品顺序排列的轻量趋势报告数组。
 * 参数 metricId：当前选择的核心指标 ID。
 * 参数 granularity：当前报告粒度。
 * 参数 selectedPeriodStart：当前选中报告的开始日期，用于标记趋势中的当前点。
 * 参数 range：趋势查询的自然日期范围。
 * 参数 errors：各竞品趋势是否读取失败。
 * 返回值：无；直接更新趋势标题、范围说明和 ECharts 图表。
 */
export function renderTrendChart(reports, metricId, granularity, selectedPeriodStart = "", range = {}, errors = []) {
  const points = comparisonTrendPoints(reports, metricId, granularity, range);
  const missingSeries = buildMissingTrendSeries(points);
  const availablePoints = points.filter((item) => item.metric && (item.selfValue != null || item.competitorValues.some((value) => value != null)));
  if (!availablePoints.length) {
    showTrendState(errors.some(Boolean) ? "趋势数据读取失败，请重试" : "当前范围暂无可用趋势数据", errors.some(Boolean));
    return;
  }

  const metric = availablePoints[0].metric;
  document.querySelector("#trend-title").textContent = `${metric.label || "指标"}趋势`;
  if (availablePoints.length < 2) {
    showTrendState("当前只有 1 个周期的数据，至少需要 2 个周期才能形成趋势");
    return;
  }
  const selectedItem = points.find((item) => item.periodStart === selectedPeriodStart);
  const target = document.querySelector("#trend-chart");
  disposeTrendChart();
  target.innerHTML = "";
  const missingLabels = points.filter((item) => item.missing || item.missingCompetitors.length).map((item) => `${item.label} ${item.missing ? "全部" : item.missingCompetitors.join("、")}`);
  target.setAttribute(
    "aria-label",
    `${metric.label || "指标"}本品与竞品趋势图${selectedItem ? `，当前选中 ${selectedItem.label}` : ""}${missingLabels.length ? `，无数据日期 ${missingLabels.join("、")}` : ""}`
  );
  trendChartInstance = echarts.init(target, null, { renderer: "svg" });
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  trendChartInstance.setOption({
    animationDuration: reduceMotion ? 0 : 420,
    color: ["#0f7b73", "#b96905", "#667085"],
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: "rgba(255, 253, 248, 0.97)",
      borderColor: "#ded6c8",
      borderWidth: 1,
      textStyle: { color: "#1f2933", fontSize: 12 },
      formatter(params) {
        const rows = Array.isArray(params) ? params : [params];
        const index = rows[0]?.dataIndex ?? 0;
        const item = points[index];
        return `
          <strong>${escapeHtml(item.period)}</strong><br>
          本品　<b>${escapeHtml(formatValue(item.selfValue, metric.unit))}</b><br>
          ${item.competitorValues.map((value, index) => `竞品 ${index + 1}　<b>${errors[index] ? "读取失败" : value == null ? "无数据" : escapeHtml(formatValue(value, metric.unit))}</b>`).join("<br>")}
        `;
      }
    },
    legend: {
      top: 0,
      right: 4,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: "#667085", fontSize: 12 },
      data: ["本品", ...reports.map((_, index) => `竞品 ${index + 1}${errors[index] ? "（读取失败）" : ""}`)]
    },
    grid: { top: 36, right: 18, bottom: 8, left: 8, containLabel: true },
    xAxis: {
      type: "category",
      boundaryGap: points.length === 1,
      data: points.map((item) => {
        if (item.missing) return `${item.label}\n—`;
        if (item.reportStatus === "ai_failed") return `${item.label}\n!`;
        if (granularity !== "day" && item.qualityStatus === "partial") return `${item.label}\n▲`;
        return item.label;
      }),
      axisLine: { lineStyle: { color: "#ded6c8" } },
      axisTick: { show: false },
      axisLabel: { color: "#667085", fontSize: 11, margin: 12 }
    },
    yAxis: {
      type: "value",
      min: 0,
      splitNumber: 4,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: "#667085", fontSize: 11, formatter: compactNumber },
      splitLine: { lineStyle: { color: "#ded6c8", type: "dashed" } }
    },
    series: [
      ...(missingSeries ? [missingSeries] : []),
      {
        name: "本品",
        type: "line",
        smooth: 0.35,
        symbol: "circle",
        symbolSize: 7,
        showSymbol: true,
        connectNulls: false,
        lineStyle: { width: 3 },
        data: points.map((item) => item.selfValue == null ? null : item.periodStart === selectedPeriodStart ? {
          value: item.selfValue,
          symbolSize: 11,
          itemStyle: { borderColor: "#fffdf8", borderWidth: 3, shadowBlur: 6, shadowColor: "rgba(15, 123, 115, 0.28)" }
        } : item.selfValue)
      },
      ...reports.map((_, index) => ({
        name: `竞品 ${index + 1}${errors[index] ? "（读取失败）" : ""}`,
        type: "line",
        smooth: 0.35,
        symbol: "circle",
        symbolSize: 7,
        showSymbol: true,
        connectNulls: false,
        lineStyle: { width: 3 },
        data: points.map((item) => item.competitorValues[index] == null ? null : item.periodStart === selectedPeriodStart ? {
          value: item.competitorValues[index],
          symbolSize: 11,
          itemStyle: { borderColor: "#fffdf8", borderWidth: 3, shadowBlur: 6, shadowColor: "rgba(185, 105, 5, 0.25)" }
        } : item.competitorValues[index])
      }))
    ]
  });
  if (typeof ResizeObserver === "function") {
    trendResizeObserver = new ResizeObserver(() => trendChartInstance?.resize());
    trendResizeObserver.observe(target);
  }
}

/**
 * 功能说明：将同一本品同一周期的竞品报告并排渲染到看板。
 * 参数 slots：各竞品商品对、报告、索引与读取状态。
 * 参数 activeMetricId：当前选中的趋势指标 ID。
 * 返回值：无；直接更新页面内容。
 */
export function renderDashboard(slots, activeMetricId = "") {
  const data = slots.find((slot) => slot.report)?.report;
  if (!data) return;
  dashboardState.slots = slots;
  dashboardState.data = { ...data, tabs: comparisonTabs(slots) };
  dashboardState.dimensions = {};
  const meta = data.meta || {};
  document.querySelector("#title").textContent = meta.title || "竞品准真实值看板";
  const count = slots.length;
  document.querySelector("#dashboard").style.setProperty("--comparison-count", count);
  const summaries = document.querySelector("#hero-summaries");
  summaries.innerHTML = slots.map((slot, index) => {
    const report = slot.report;
    const current = report?.meta || {};
    const metrics = report?.core_metrics || [];
    const advantage = hasDetailPoints(current.summary_detail) ? current.summary : compactHeroSummary(metrics, "advantage");
    const weakness = hasDetailPoints(current.weakness_summary_detail) ? current.weakness_summary : compactHeroSummary(metrics, "warning");
    return `<button class="hero comparison-hero" type="button" data-summary-index="${index}" ${report ? 'aria-haspopup="dialog" aria-controls="summary-dialog"' : "disabled"}>
      <span class="comparison-label">对比竞品 ${index + 1}</span>
      ${report ? `<span class="hero-block"><span class="hero-label warning">弱点</span><span class="weakness-text">${escapeHtml(weakness)}</span></span>
      <span class="hero-block"><span class="hero-label advantage">优点</span><span class="summary">${escapeHtml(advantage)}</span></span>`
      : `<span class="empty-inline">${slot.error ? "报告读取失败" : "所选周期暂无报告"}</span>`}
    </button>`;
  }).join("");
  summaries.querySelectorAll("[data-summary-index]").forEach((button) => {
    const slot = slots[Number(button.dataset.summaryIndex)];
    if (!slot.report) return;
    const current = slot.report.meta || {};
    button.dataset.advantageDetail = JSON.stringify(hasDetailPoints(current.summary_detail) ? current.summary_detail : current.summary || "-");
    button.dataset.weaknessDetail = JSON.stringify(hasDetailPoints(current.weakness_summary_detail) ? current.weakness_summary_detail : current.weakness_summary || "-");
    button.dataset.dialogTitle = `对比竞品 ${Number(button.dataset.summaryIndex) + 1} · 优缺点`;
  });
  bindHeroSummaryDialog(document.querySelector("#summary-dialog"), summaries);
  const metricItems = comparisonMetrics(slots);
  const preferred = activeMetricId || dashboardState.activeMetricId;
  dashboardState.activeMetricId = metricItems.some((item) => item.id === preferred) ? preferred : metricItems[0]?.id || "";
  const metrics = document.querySelector("#metrics");
  metrics.innerHTML = metricItems.map((item) => {
    const statusClass = item.comparisons.some((metric) => metric?.status === "warning") ? "warning" : "advantage";
    return `<button class="metric-card status-${statusClass} ${item.id === dashboardState.activeMetricId ? "active" : ""}" type="button" data-metric-id="${escapeHtml(item.id)}" aria-pressed="${item.id === dashboardState.activeMetricId}">
      <p class="metric-title">${escapeHtml(item.label)}</p>
      <div class="metric-values">
        <div><div class="metric-value self">${escapeHtml(formatValue(item.self_value, item.unit))}</div><div class="metric-sub">本品</div></div>
        ${item.comparisons.map((metric, index) => `<div><div class="metric-value competitor">${escapeHtml(formatValue(metric?.competitor_value, item.unit))}</div><div class="metric-sub">竞品 ${index + 1}</div></div>`).join("")}
      </div>
      <div class="comparison-gaps">${item.comparisons.map((metric, index) => `<div class="comparison-gap ${metric?.status === "warning" ? "warning" : "advantage"}"><span>对竞品 ${index + 1}</span><strong>${metric ? escapeHtml(formatMetricGap(metric)) : "—"}${metric && formatMetricAmplitude(metric) ? ` <span class="metric-gap-divider" aria-hidden="true"></span> ${escapeHtml(formatMetricAmplitude(metric))}` : ""}</strong></div>`).join("")}</div>
    </button>`;
  }).join("");
  metrics.querySelectorAll("[data-metric-id]").forEach((button) => {
    button.addEventListener("click", () => {
      dashboardState.activeMetricId = button.dataset.metricId;
      metrics.querySelectorAll("[data-metric-id]").forEach((item) => {
        const active = item.dataset.metricId === dashboardState.activeMetricId;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      document.dispatchEvent(new CustomEvent("dashboard:metric-select", { detail: { metricId: dashboardState.activeMetricId } }));
    });
  });
  renderTabs();
  renderAiRecommendations();
  document.querySelector("#risks").textContent = slots.map((slot, index) => slot.report?.risks?.length
    ? `竞品 ${index + 1}：${slot.report.risks.join("；")}` : "").filter(Boolean).join("。");
  document.querySelector("#page-state").hidden = true;
  document.querySelector("#dashboard").hidden = false;
}

export function showPageState(message, isError = false) {
  const state = document.querySelector("#page-state");
  state.hidden = false;
  state.classList.toggle("error", isError);
  state.textContent = message;
  document.querySelector("#dashboard").hidden = true;
}
