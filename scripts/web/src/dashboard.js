const granularityLabels = {
  day: "日",
  week: "周",
  month: "月"
};

const dashboardState = {
  data: null,
  activeTab: 0,
  activeMetricId: "",
  filter: "",
  dimensions: {}
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
  if (value == null || value === "" || value === "-") {
    return "-";
  }
  if (typeof value === "number") {
    const text = Number.isInteger(value)
      ? value.toLocaleString("zh-CN")
      : value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${text}${unit}`;
  }
  return `${value}${unit}`;
}

/**
 * 功能说明：把核心指标差值压缩为带方向符号的纯数字。
 * 参数 item：核心指标卡数据。
 * 返回值：领先为正数、落后为负数的简短差值文本。
 */
function formatMetricGap(item) {
  if (item.gap_abs_text == null || item.gap_abs_text === "") {
    return "-";
  }
  const value = String(item.gap_abs_text).replace(/^[+-]/, "");
  const sign = item.status === "warning" ? "-" : "+";
  const unit = item.id === "conversion_rate" ? "pct" : "";
  return `${sign}${value}${unit}`;
}

/**
 * 功能说明：从核心指标倍率说明中提取纯倍率数字。
 * 参数 item：核心指标卡数据。
 * 返回值：不包含本品或竞品说明的倍率文本。
 */
function formatMetricRatio(item) {
  const match = String(item.ratio_text || "").match(/(\d+(?:\.\d+)?)x/i);
  return match ? `${match[1]}x` : "-";
}

function valueTone(value, column = {}) {
  const text = String(value ?? "");
  const key = String(column.key || "");
  if (/落后|竞品独有|补词机会|成交落后|访客落后|短板/.test(text)) {
    return "cell-bad";
  }
  if (/领先|本品独有|本品优势|优势|保持优势/.test(text)) {
    return "cell-good";
  }
  if (typeof value === "number" && /(gap|差距|visitor_gap|gmv_gap|order_gap|gap_rate)/.test(key)) {
    return value > 0 ? "cell-good" : value < 0 ? "cell-bad" : "cell-neutral";
  }
  return value == null || text === "-" ? "cell-neutral" : "";
}

function renderCell(row, column) {
  const value = row[column.key];
  return `<span class="${valueTone(value, column)}">${escapeHtml(formatValue(value, column.unit || ""))}</span>`;
}

function renderTabs() {
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
      dashboardState.filter = "";
      renderTabs();
    });
  });

  const current = tabs[dashboardState.activeTab] || tabs[0] || {};
  const highlights = current.highlights || [];
  const rows = current.rows || [];
  const columns = current.columns || [];
  const dimensionField = current.dimension_field;
  const dimensionOptions = dimensionField
    ? [...new Set(rows.map((row) => row[dimensionField]).filter(Boolean))]
    : [];
  const activeDimension = dashboardState.dimensions[current.id] || dimensionOptions[0] || "";
  const dimensionRows = activeDimension
    ? rows.filter((row) => row[dimensionField] === activeDimension)
    : rows;
  const query = dashboardState.filter.trim().toLowerCase();
  const filteredRows = query
    ? dimensionRows.filter((row) => Object.values(row).some((value) => String(value ?? "").toLowerCase().includes(query)))
    : dimensionRows;

  document.querySelector("#tab-body").innerHTML = `
    <h3>${escapeHtml(current.headline || "-")}</h3>
    <section class="tab-section">
      <p class="section-title">AI建议重点</p>
      <div class="insight-grid">
        ${highlights.map((item) => `
          <article class="insight-card ${item.status === "warning" ? "warning" : "advantage"}">
            <h4>${escapeHtml(item.label || "-")}</h4>
            <p class="insight-gap">${escapeHtml(item.gap_text || "-")}</p>
            ${item.action ? `<p>${escapeHtml(item.action)}</p>` : ""}
          </article>
        `).join("") || '<p class="empty-inline">当前周期暂无重点数据</p>'}
      </div>
    </section>
    <section class="tab-section">
      <div class="table-tools">
        <p class="section-title">完整数据对比</p>
        <input class="data-filter" id="data-filter" type="search" placeholder="筛选当前表格" value="${escapeHtml(dashboardState.filter)}">
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
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
          <tbody>
            ${filteredRows.map((row) => `
              <tr>${columns.map((column) => `<td>${renderCell(row, column)}</td>`).join("")}</tr>
            `).join("") || `<tr><td class="empty-cell" colspan="${Math.max(columns.length, 1)}">没有符合条件的数据</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
    ${(current.notes || []).length ? `<ul class="notes">${current.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>` : ""}
  `;

  document.querySelector("#data-filter")?.addEventListener("input", (event) => {
    dashboardState.filter = event.target.value;
    renderTabs();
    document.querySelector("#data-filter")?.focus();
  });
  document.querySelectorAll("[data-dimension]").forEach((button) => {
    button.addEventListener("click", () => {
      dashboardState.dimensions[current.id] = button.dataset.dimension;
      dashboardState.filter = "";
      renderTabs();
    });
  });
}

function renderDiagnosis() {
  const target = document.querySelector("#diagnosis");
  const diagnosis = dashboardState.data?.diagnosis || [];
  target.innerHTML = diagnosis.map((item) => `
    <section class="diagnosis-card ${item.status === "warning" ? "warning" : "advantage"}">
      <h3>${escapeHtml(item.title || "-")}</h3>
      <p class="diagnosis-evidence">${escapeHtml(item.evidence || item.text || "-")}</p>
      ${item.recommendation ? `
        <div class="diagnosis-advice">
          <span>建议</span>
          <p>${escapeHtml(item.recommendation)}</p>
        </div>
      ` : ""}
    </section>
  `).join("") || '<p class="empty-inline">当前周期暂无诊断建议</p>';
}

function compactNumber(value) {
  const absolute = Math.abs(value);
  if (absolute >= 1000000) {
    return `${(value / 1000000).toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (absolute >= 1000) {
    return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function niceMaximum(value) {
  if (!Number.isFinite(value) || value <= 0) {
    return 1;
  }
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

function smoothPath(points) {
  if (points.length < 2) {
    return "";
  }
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const middleX = (current.x + next.x) / 2;
    path += ` C ${middleX} ${current.y}, ${middleX} ${next.y}, ${next.x} ${next.y}`;
  }
  return path;
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

/**
 * 功能说明：显示趋势图加载、空数据或错误状态。
 * 参数 message：需要显示的状态文本。
 * 参数 isError：是否使用错误提示语义。
 * 返回值：无；直接更新趋势图容器。
 */
export function showTrendState(message, isError = false) {
  const target = document.querySelector("#trend-chart");
  target.innerHTML = `<div class="trend-empty ${isError ? "error" : ""}">${escapeHtml(message)}</div>`;
}

/**
 * 功能说明：使用多个周期的分析结果绘制本品和竞品趋势折线图。
 * 参数 reports：按时间升序排列的 `analysis_result.json` 数组。
 * 参数 metricId：当前选择的核心指标 ID。
 * 参数 granularity：当前报告粒度。
 * 返回值：无；直接更新趋势标题、范围说明和 SVG 图表。
 */
export function renderTrendChart(reports, metricId, granularity) {
  const series = reports.map((report) => {
    const metric = (report.core_metrics || []).find((item) => item.id === metricId);
    if (!metric || typeof metric.self_value !== "number" || typeof metric.competitor_value !== "number") {
      return null;
    }
    return {
      period: report.meta?.period || "-",
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
  const scopeLabels = { day: `近 ${series.length} 天`, week: `本月 ${series.length} 周`, month: `${series.length} 个月` };
  document.querySelector("#trend-title").textContent = `${metric.label || "指标"}趋势`;
  document.querySelector("#trend-scope").textContent = `${scopeLabels[granularity] || `${series.length} 个周期`} · 点击上方指标切换`;

  const width = 1100;
  const height = 310;
  const margin = { top: 18, right: 24, bottom: 48, left: 68 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const maximum = niceMaximum(Math.max(...series.flatMap((item) => [item.selfValue, item.competitorValue])));
  const xAt = (index) => series.length === 1
    ? margin.left + plotWidth / 2
    : margin.left + (plotWidth * index) / (series.length - 1);
  const yAt = (value) => margin.top + plotHeight - (value / maximum) * plotHeight;
  const selfPoints = series.map((item, index) => ({ x: xAt(index), y: yAt(item.selfValue) }));
  const competitorPoints = series.map((item, index) => ({ x: xAt(index), y: yAt(item.competitorValue) }));
  const ticks = Array.from({ length: 5 }, (_, index) => (maximum * index) / 4);
  const hitWidth = plotWidth / Math.max(series.length, 1);

  const target = document.querySelector("#trend-chart");
  target.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(metric.label || "指标")}本品与竞品趋势图">
      ${ticks.map((tick) => {
        const y = yAt(tick);
        return `
          <line class="trend-grid-line" x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}"></line>
          <text class="trend-axis-label" x="${margin.left - 12}" y="${y + 4}" text-anchor="end">${escapeHtml(compactNumber(tick))}</text>
        `;
      }).join("")}
      ${series.map((item, index) => `
        <text class="trend-axis-label" x="${xAt(index)}" y="${height - 15}" text-anchor="middle">${escapeHtml(item.label)}</text>
      `).join("")}
      ${series.length > 1 ? `<path class="trend-line self" d="${smoothPath(selfPoints)}"></path>` : ""}
      ${series.length > 1 ? `<path class="trend-line competitor" d="${smoothPath(competitorPoints)}"></path>` : ""}
      ${selfPoints.map((point) => `<circle class="trend-point self" cx="${point.x}" cy="${point.y}" r="5"></circle>`).join("")}
      ${competitorPoints.map((point) => `<circle class="trend-point competitor" cx="${point.x}" cy="${point.y}" r="5"></circle>`).join("")}
      ${series.map((item, index) => {
        const hitLeft = Math.max(margin.left, xAt(index) - hitWidth / 2);
        const hitRight = Math.min(width - margin.right, xAt(index) + hitWidth / 2);
        return `
          <rect class="trend-hit-area" data-trend-index="${index}" x="${hitLeft}" y="${margin.top}" width="${hitRight - hitLeft}" height="${plotHeight}" tabindex="0">
            <title>${escapeHtml(`${item.period}；本品 ${formatValue(item.selfValue, metric.unit)}；竞品 ${formatValue(item.competitorValue, metric.unit)}`)}</title>
          </rect>
        `;
      }).join("")}
    </svg>
    <div class="trend-tooltip" id="trend-tooltip" hidden></div>
  `;

  const tooltip = document.querySelector("#trend-tooltip");
  const showTooltip = (index) => {
    const item = series[index];
    const top = Math.max(72, Math.min(selfPoints[index].y, competitorPoints[index].y));
    tooltip.innerHTML = `
      <strong>${escapeHtml(item.period)}</strong>
      <div class="trend-tooltip-row self"><span>本品</span><b>${escapeHtml(formatValue(item.selfValue, metric.unit))}</b></div>
      <div class="trend-tooltip-row competitor"><span>竞品</span><b>${escapeHtml(formatValue(item.competitorValue, metric.unit))}</b></div>
    `;
    tooltip.style.left = `${(xAt(index) / width) * 100}%`;
    tooltip.style.top = `${(top / height) * 100}%`;
    tooltip.hidden = false;
  };
  target.querySelectorAll("[data-trend-index]").forEach((area) => {
    const index = Number(area.dataset.trendIndex);
    area.addEventListener("mouseenter", () => showTooltip(index));
    area.addEventListener("focus", () => showTooltip(index));
    area.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    area.addEventListener("blur", () => { tooltip.hidden = true; });
  });
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
    meta.granularity ? `分析粒度：${granularityLabels[meta.granularity] || meta.granularity}` : "",
    meta.self_spu ? `本品 SPU ${meta.self_spu}` : "",
    meta.competitor_spu ? `竞品 SPU ${meta.competitor_spu}` : ""
  ].filter(Boolean).join(" | ");
  document.querySelector("#summary").textContent = meta.summary || "-";
  document.querySelector("#weakness").textContent = meta.weakness_summary || "-";
  const metricItems = data.core_metrics || [];
  const preferredMetricId = activeMetricId || dashboardState.activeMetricId;
  dashboardState.activeMetricId = metricItems.some((item) => item.id === preferredMetricId)
    ? preferredMetricId
    : metricItems[0]?.id || "";
  const metrics = document.querySelector("#metrics");
  metrics.innerHTML = metricItems.map((item) => {
    const selfText = formatValue(item.self_value, item.unit);
    const competitorText = formatValue(item.competitor_value, item.unit);
    return `
      <button class="metric-card ${item.id === dashboardState.activeMetricId ? "active" : ""}" type="button" data-metric-id="${escapeHtml(item.id)}" aria-pressed="${item.id === dashboardState.activeMetricId}">
        <p class="metric-title">${escapeHtml(item.label || "-")}</p>
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
        <div class="metric-gap ${item.status === "warning" ? "warning" : "advantage"}">
          <span>${escapeHtml(formatMetricGap(item))}</span>
          <span class="metric-gap-divider" aria-hidden="true"></span>
          <span>${escapeHtml(formatMetricRatio(item))}</span>
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
  renderDiagnosis();
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
