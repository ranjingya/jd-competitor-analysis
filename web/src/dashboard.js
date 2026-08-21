import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import { mountAnalysisVxeTable, unmountAnalysisVxeTable } from "./analysis-vxe-table.js";
import { compactHeroSummary } from "./hero-summary.js";

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer]);

const granularityLabels = {
  day: "日",
  week: "周",
  month: "月"
};

const dashboardState = {
  data: null,
  activeTab: 0,
  activeMetricId: "",
  dimensions: {},
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

/**
 * 功能说明：标准化报告中的商品引用，兼容只包含旧版商品字段的报告。
 * 参数 meta：分析结果中的元信息对象。
 * 参数 role：商品角色，取值为 self 或 competitor。
 * 返回值：包含商品 ID、名称、主图和京东详情地址的展示对象。
 */
function normalizeProductReference(meta, role) {
  const reference = meta?.[`${role}_product`] || {};
  const id = String(reference.id || meta?.[`${role}_spu`] || "").trim();
  const fallbackName = role === "self" ? "本品" : "竞品";
  return {
    id,
    name: String(reference.name || meta?.[`${role}_name`] || fallbackName).trim(),
    imageUrl: String(reference.image_url || "").trim(),
    itemUrl: id ? `https://item.jd.com/${encodeURIComponent(id)}.html` : ""
  };
}

/**
 * 功能说明：渲染本品与竞品商品条，并为图片加载失败提供稳定占位。
 * 参数 meta：分析结果中的元信息对象。
 * 返回值：无；直接更新页头商品区域。
 */
function renderProductComparison(meta) {
  const target = document.querySelector("#product-comparison");
  if (!target) {
    return;
  }
  const products = [
    { role: "self", label: "本品", ...normalizeProductReference(meta, "self") },
    { role: "competitor", label: "竞品", ...normalizeProductReference(meta, "competitor") }
  ];
  target.innerHTML = products.map((product, index) => {
    const image = product.imageUrl
      ? `<img class="product-image" data-product-image src="${escapeHtml(product.imageUrl)}" alt="${escapeHtml(product.name)}主图" loading="eager" referrerpolicy="no-referrer">`
      : "";
    const content = `
      <span class="product-image-frame ${product.imageUrl ? "has-image" : ""}">
        ${image}
        <span class="product-image-fallback" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M4 5.5h16v13H4zM7.5 15l3.1-3.4 2.4 2.5 1.7-1.7 2.8 2.6M16.5 8.7h.01" />
          </svg>
          <span>暂无主图</span>
        </span>
      </span>
      <span class="product-card-copy">
        <span class="product-card-topline">
          <span class="product-role product-role-${product.role}">${product.label}</span>
          <span class="product-name" title="${escapeHtml(product.name)}">${escapeHtml(product.name)}</span>
        </span>
        <span class="product-id">商品 ID ${escapeHtml(product.id || "未配置")}</span>
      </span>`;
    const card = product.itemUrl
      ? `<a class="product-card" href="${escapeHtml(product.itemUrl)}" target="_blank" rel="noopener noreferrer" aria-label="在京东打开${product.label}：${escapeHtml(product.name)}">${content}</a>`
      : `<span class="product-card product-card-disabled">${content}</span>`;
    const divider = index === 0 ? `<span class="product-compare-marker" aria-hidden="true">VS</span>` : "";
    return `${card}${divider}`;
  }).join("");
  target.querySelectorAll("[data-product-image]").forEach((imageElement) => {
    imageElement.addEventListener("error", () => {
      imageElement.hidden = true;
      imageElement.closest(".product-image-frame")?.classList.remove("has-image");
    }, { once: true });
  });
}

function formatValue(value, unit = "") {
  if (value == null || value === "" || value === "-") {
    return "-";
  }
  if (typeof value === "number") {
    return `${value.toFixed(2)}${unit}`;
  }
  return `${value}${unit}`;
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
  const highlights = current.highlights || [];
  const rows = current.rows || [];
  const columns = current.columns || [];
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
      <p class="section-title">优势与劣势</p>
      <div class="insight-grid">
        ${highlights.map((item) => {
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
    </section>
    <section class="tab-section">
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
  if (tableTarget) {
    mountAnalysisVxeTable(tableTarget, {
      id: current.id,
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
  const suggestions = (dashboardState.data?.ai_recommendations || [])
    .filter((item) => item.status === "warning")
    .slice(0, 5);
  target.innerHTML = suggestions.map((item) => {
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

function trendPeriodLabel(meta, granularity) {
  const start = String(meta.period_start || "");
  const end = String(meta.period_end || "");
  if (granularity === "month") {
    return start.slice(0, 7) || meta.period || "-";
  }
  if (granularity === "week" && end && end !== start) {
    return `${start.slice(5)}~${end.slice(5)}`;
  }
  return start.slice(5) || meta.period || "-";
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
 * 参数 reports：按时间升序排列的 `analysis_result.json` 数组。
 * 参数 metricId：当前选择的核心指标 ID。
 * 参数 granularity：当前报告粒度。
 * 参数 selectedPeriodStart：当前选中报告的开始日期，用于标记趋势中的当前点。
 * 返回值：无；直接更新趋势标题、范围说明和 ECharts 图表。
 */
export function renderTrendChart(reports, metricId, granularity, selectedPeriodStart = "") {
  const series = reports.map((report) => {
    const metric = (report.core_metrics || []).find((item) => item.id === metricId);
    if (!metric || typeof metric.self_value !== "number" || typeof metric.competitor_value !== "number") {
      return null;
    }
    return {
      period: report.meta?.period || "-",
      periodStart: String(report.meta?.period_start || ""),
      label: trendPeriodLabel(report.meta || {}, granularity),
      selfValue: metric.self_value,
      competitorValue: metric.competitor_value,
      metric
    };
  }).filter(Boolean);
  if (!series.length) {
    showTrendState("当前范围暂无可用趋势数据");
    return;
  }

  const metric = series[0].metric;
  document.querySelector("#trend-title").textContent = `${metric.label || "指标"}趋势`;
  if (series.length < 2) {
    showTrendState("当前只有 1 个周期的数据，至少需要 2 个周期才能形成趋势");
    return;
  }
  const selectedItem = series.find((item) => item.periodStart === selectedPeriodStart);
  const target = document.querySelector("#trend-chart");
  disposeTrendChart();
  target.innerHTML = "";
  target.setAttribute("aria-label", `${metric.label || "指标"}本品与竞品趋势图${selectedItem ? `，当前选中 ${selectedItem.label}` : ""}`);
  trendChartInstance = echarts.init(target, null, { renderer: "svg" });
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  trendChartInstance.setOption({
    animationDuration: reduceMotion ? 0 : 420,
    color: ["#0f7b73", "#b96905"],
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
        const item = series[index];
        return `
          <strong>${escapeHtml(item.period)}</strong><br>
          ${rows.map((row) => `${row.marker}${escapeHtml(row.seriesName)}　<b>${escapeHtml(formatValue(row.value, metric.unit))}</b>`).join("<br>")}
        `;
      }
    },
    legend: {
      top: 0,
      right: 4,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: "#667085", fontSize: 12 },
      data: ["本品", "竞品"]
    },
    grid: { top: 36, right: 18, bottom: 8, left: 8, containLabel: true },
    xAxis: {
      type: "category",
      boundaryGap: series.length === 1,
      data: series.map((item) => item.label),
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
      {
        name: "本品",
        type: "line",
        smooth: 0.35,
        symbol: "circle",
        symbolSize: 7,
        showSymbol: true,
        lineStyle: { width: 3 },
        data: series.map((item) => item.periodStart === selectedPeriodStart ? {
          value: item.selfValue,
          symbolSize: 11,
          itemStyle: { borderColor: "#fffdf8", borderWidth: 3, shadowBlur: 6, shadowColor: "rgba(15, 123, 115, 0.28)" }
        } : item.selfValue)
      },
      {
        name: "竞品",
        type: "line",
        smooth: 0.35,
        symbol: "circle",
        symbolSize: 7,
        showSymbol: true,
        lineStyle: { width: 3 },
        data: series.map((item) => item.periodStart === selectedPeriodStart ? {
          value: item.competitorValue,
          symbolSize: 11,
          itemStyle: { borderColor: "#fffdf8", borderWidth: 3, shadowBlur: 6, shadowColor: "rgba(185, 105, 5, 0.25)" }
        } : item.competitorValue)
      }
    ]
  });
  if (typeof ResizeObserver === "function") {
    trendResizeObserver = new ResizeObserver(() => trendChartInstance?.resize());
    trendResizeObserver.observe(target);
  }
}

/**
 * 功能说明：把一份分析结果渲染到看板。
 * 参数 data：当前粒度和周期的 `analysis_result.json`。
 * 参数 activeMetricId：当前选中的趋势指标 ID。
 * 返回值：无；直接更新页面内容。
 */
export function renderDashboard(data, activeMetricId = "") {
  dashboardState.data = data;
  dashboardState.filter = "";
  dashboardState.dimensions = {};
  const meta = data.meta || {};
  document.querySelector("#title").textContent = meta.title || "竞品准真实值看板";
  document.querySelector("#meta").textContent = [
    meta.period,
    meta.granularity ? `分析粒度：${granularityLabels[meta.granularity] || meta.granularity}` : ""
  ].filter(Boolean).join(" · ");
  renderProductComparison(meta);
  const summary = meta.summary || "-";
  const weakness = meta.weakness_summary || "-";
  const metricItems = data.core_metrics || [];
  const hasStructuredSummary = Boolean(meta.summary_detail || meta.weakness_summary_detail);
  document.querySelector("#summary").textContent = hasStructuredSummary
    ? summary
    : compactHeroSummary(metricItems, "advantage");
  document.querySelector("#weakness").textContent = hasStructuredSummary
    ? weakness
    : compactHeroSummary(metricItems, "warning");
  const heroTrigger = document.querySelector("#hero-summary-trigger");
  heroTrigger.dataset.advantageDetail = JSON.stringify(meta.summary_detail || summary);
  heroTrigger.dataset.weaknessDetail = JSON.stringify(meta.weakness_summary_detail || weakness);
  const preferredMetricId = activeMetricId || dashboardState.activeMetricId;
  dashboardState.activeMetricId = metricItems.some((item) => item.id === preferredMetricId)
    ? preferredMetricId
    : metricItems[0]?.id || "";
  const metrics = document.querySelector("#metrics");
  metrics.innerHTML = metricItems.map((item) => {
    const selfText = formatValue(item.self_value, item.unit);
    const competitorText = formatValue(item.competitor_value, item.unit);
    const amplitudeText = formatMetricAmplitude(item);
    const statusClass = item.status === "warning" ? "warning" : "advantage";
    return `
      <button class="metric-card status-${statusClass} ${item.id === dashboardState.activeMetricId ? "active" : ""}" type="button" data-metric-id="${escapeHtml(item.id)}" aria-pressed="${item.id === dashboardState.activeMetricId}">
        <div class="metric-card-head">
          <p class="metric-title">${escapeHtml(item.label || "-")}</p>
          <div class="metric-gap">
            <span>${escapeHtml(formatMetricGap(item))}</span>
            ${amplitudeText ? `
              <span class="metric-gap-divider" aria-hidden="true"></span>
              <span>${escapeHtml(amplitudeText)}</span>
            ` : ""}
          </div>
        </div>
        <div class="metric-values">
          <div>
            <div class="metric-value self">${escapeHtml(selfText)}</div>
            <div class="metric-sub">本品真实值</div>
          </div>
          <div>
            <div class="metric-value competitor">${escapeHtml(competitorText)}</div>
            <div class="metric-sub">竞品估算值</div>
          </div>
        </div>
      </button>
    `;
  }).join("");
  metrics.querySelectorAll("[data-metric-id]").forEach((button) => {
    button.addEventListener("click", () => {
      dashboardState.activeMetricId = button.dataset.metricId;
      metrics.querySelectorAll("[data-metric-id]").forEach((item) => {
        const isActive = item.dataset.metricId === dashboardState.activeMetricId;
        item.classList.toggle("active", isActive);
        item.setAttribute("aria-pressed", String(isActive));
      });
      document.dispatchEvent(new CustomEvent("dashboard:metric-select", {
        detail: { metricId: dashboardState.activeMetricId }
      }));
    });
  });
  renderTabs();
  renderAiRecommendations();
  document.querySelector("#risks").textContent = `风险提示：${(data.risks || ["暂无"]).join("；")}`;
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
