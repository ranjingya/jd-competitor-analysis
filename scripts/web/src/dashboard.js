const granularityLabels = {
  day: "日",
  week: "周",
  month: "月"
};

const dashboardState = {
  data: null,
  activeTab: 0,
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

/**
 * 功能说明：把一份分析结果渲染到看板。
 * 参数 data：当前粒度和周期的 `analysis_result.json`。
 * 返回值：无；直接更新页面内容。
 */
export function renderDashboard(data) {
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
  document.querySelector("#metrics").innerHTML = (data.core_metrics || []).map((item) => {
    const selfText = formatValue(item.self_value, item.unit);
    const competitorText = formatValue(item.competitor_value, item.unit);
    return `
      <article class="metric-card">
        <p class="metric-title">${escapeHtml(item.label || "-")}</p>
        <div class="metric-values">
          <div>
            <div class="metric-value self ${selfText.length > 7 ? "long" : ""}">${escapeHtml(selfText)}</div>
            <div class="metric-sub">本品真实值</div>
          </div>
          <div>
            <div class="metric-value competitor ${competitorText.length > 7 ? "long" : ""}">${escapeHtml(competitorText)}</div>
            <div class="metric-sub">竞品估算值</div>
          </div>
        </div>
        <div class="metric-gap ${item.status === "warning" ? "warning" : "advantage"}">${escapeHtml(item.gap_text || "-")}</div>
      </article>
    `;
  }).join("");
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
