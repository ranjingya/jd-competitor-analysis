import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

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
  sorts: {},
  expandedTrafficPaths: new Set(),
  trafficTreeKey: "",
  renderedTableKey: ""
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
  return `${value}${unit}`;
}

/**
 * 功能说明：计算重点卡的带方向差值。
 * 参数 item：包含本品值、竞品值和单位的重点数据。
 * 返回值：带正负方向和展示单位的差值文本。
 */
function formatHighlightGap(item) {
  const selfValue = typeof item.self_value === "number" ? item.self_value : 0;
  const competitorValue = typeof item.competitor_value === "number" ? item.competitor_value : 0;
  const gap = selfValue - competitorValue;
  const sign = gap > 0 ? "+" : "";
  const unit = item.unit === "%" ? "pct" : (item.unit || "");
  return `${sign}${gap.toFixed(2)}${unit}`;
}

/**
 * 功能说明：计算重点卡的强弱倍率或独有状态。
 * 参数 item：包含本品值和竞品值的重点数据。
 * 返回值：倍率、独有状态或无可比标识。
 */
function formatHighlightRatio(item) {
  const selfValue = typeof item.self_value === "number" ? item.self_value : 0;
  const competitorValue = typeof item.competitor_value === "number" ? item.competitor_value : 0;
  if (selfValue > 0 && competitorValue > 0) {
    return `${(Math.max(selfValue, competitorValue) / Math.min(selfValue, competitorValue)).toFixed(2)}x`;
  }
  if (selfValue > 0) {
    return "本品独有";
  }
  if (competitorValue > 0) {
    return "竞品独有";
  }
  return "-";
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
  const rawValue = String(item.gap_abs_text).replaceAll(",", "").replace(/^[+-]/, "");
  const value = Number(rawValue);
  const sign = item.status === "warning" ? "-" : "+";
  const unit = item.id === "conversion_rate" ? "pct" : "";
  return Number.isFinite(value) ? `${sign}${value.toFixed(2)}${unit}` : "-";
}

/**
 * 功能说明：从核心指标倍率说明中提取纯倍率数字。
 * 参数 item：核心指标卡数据。
 * 返回值：不包含本品或竞品说明的倍率文本。
 */
function formatMetricRatio(item) {
  const match = String(item.ratio_text || "").match(/(\d+(?:\.\d+)?)x/i);
  return match ? `${Number(match[1]).toFixed(2)}x` : "-";
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

/**
 * 功能说明：比较两行在指定列上的排序先后，并把空值固定放在末尾。
 * 参数 leftRow：左侧数据行。
 * 参数 rightRow：右侧数据行。
 * 参数 column：当前排序列定义。
 * 参数 direction：排序方向，desc 为降序，asc 为升序。
 * 返回值：适用于 Array.sort 的比较结果。
 */
function compareRows(leftRow, rightRow, column, direction) {
  const leftValue = leftRow[column.key];
  const rightValue = rightRow[column.key];
  const leftEmpty = leftValue == null || leftValue === "" || leftValue === "-";
  const rightEmpty = rightValue == null || rightValue === "" || rightValue === "-";
  if (leftEmpty || rightEmpty) {
    return leftEmpty === rightEmpty ? 0 : leftEmpty ? 1 : -1;
  }
  let result;
  if (typeof leftValue === "number" && typeof rightValue === "number") {
    result = leftValue - rightValue;
  } else {
    result = String(leftValue).localeCompare(String(rightValue), "zh-CN", { numeric: true, sensitivity: "base" });
  }
  return direction === "desc" ? -result : result;
}

/**
 * 功能说明：按当前列稳定排序普通表格行。
 * 参数 rows：待排序的数据行。
 * 参数 column：当前排序列定义；为空时保持原始顺序。
 * 参数 direction：排序方向。
 * 返回值：排序后的新数组。
 */
function sortRows(rows, column, direction) {
  if (!column || !direction) {
    return rows;
  }
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => compareRows(left.row, right.row, column, direction) || left.index - right.index)
    .map((item) => item.row);
}

/**
 * 功能说明：渲染带省略展示和完整信息 Tooltip 的冻结文本单元格。
 * 参数 row：当前表格行。
 * 参数 column：冻结首列定义。
 * 返回值：冻结列使用的 HTML 字符串。
 */
function renderFrozenTextCell(row, column) {
  const text = formatValue(row[column.key], column.unit || "");
  return `
    <span class="frozen-cell-tip" tabindex="0" data-tooltip="${escapeHtml(text)}">
      <span class="frozen-cell-label">${escapeHtml(text)}</span>
    </span>
  `;
}

/**
 * 功能说明：把流量来源行整理为可展开的渠道树，并按展开状态计算可见行。
 * 参数 rows：当前流量来源 Tab 的全部渠道行。
 * 参数 sortColumn：当前排序列定义；为空时保持原始同级顺序。
 * 参数 sortDirection：当前排序方向。
 * 返回值：包含可见行、节点元信息和父节点集合的树形渲染数据。
 */
function buildTrafficTree(rows, sortColumn, sortDirection) {
  const nodes = rows.map((row, index) => {
    const levels = [row.level_1, row.level_2, row.level_3]
      .filter((value) => value != null && value !== "" && value !== "-");
    const key = levels.join(" > ");
    return {
      row,
      index,
      key,
      label: levels.at(-1) || row.path || "-",
      depth: Math.max(levels.length - 1, 0),
      ancestors: levels.slice(0, -1).map((_, levelIndex) => levels.slice(0, levelIndex + 1).join(" > ")),
      parentKey: levels.length > 1 ? levels.slice(0, -1).join(" > ") : ""
    };
  });
  const parentKeys = new Set(nodes.flatMap((node) => node.ancestors));
  const treeKey = `${dashboardState.data?.meta?.period_key || "-"}:${nodes.map((node) => node.key).join("|")}`;
  if (dashboardState.trafficTreeKey !== treeKey) {
    dashboardState.trafficTreeKey = treeKey;
    dashboardState.expandedTrafficPaths = new Set(
      nodes.filter((node) => node.depth === 0 && parentKeys.has(node.key)).map((node) => node.key)
    );
  }

  const childrenByParent = new Map();
  nodes.forEach((node) => {
    const siblings = childrenByParent.get(node.parentKey) || [];
    siblings.push(node);
    childrenByParent.set(node.parentKey, siblings);
  });
  if (sortColumn && sortDirection) {
    childrenByParent.forEach((siblings) => {
      siblings.sort((left, right) =>
        compareRows(left.row, right.row, sortColumn, sortDirection) || left.index - right.index
      );
    });
  }
  const visibleNodes = [];
  const appendChildren = (parentKey) => {
    (childrenByParent.get(parentKey) || []).forEach((node) => {
      visibleNodes.push(node);
      if (dashboardState.expandedTrafficPaths.has(node.key)) {
        appendChildren(node.key);
      }
    });
  };
  appendChildren("");
  return {
    rows: visibleNodes.map((node) => node.row),
    metaByKey: new Map(nodes.map((node) => [node.key, { ...node, hasChildren: parentKeys.has(node.key) }]))
  };
}

/**
 * 功能说明：渲染树形渠道单元格，包含层级缩进和展开收起按钮。
 * 参数 row：当前渠道数据行。
 * 参数 tree：buildTrafficTree 返回的树形渲染数据。
 * 返回值：渠道路径首列使用的 HTML 字符串。
 */
function renderTrafficTreeCell(row, tree) {
  const key = [row.level_1, row.level_2, row.level_3]
    .filter((value) => value != null && value !== "" && value !== "-")
    .join(" > ");
  const meta = tree.metaByKey.get(key) || { key, label: row.path || "-", depth: 0, hasChildren: false };
  const expanded = dashboardState.expandedTrafficPaths.has(meta.key);
  const control = meta.hasChildren
    ? `<button class="tree-toggle" type="button" data-traffic-tree-key="${escapeHtml(meta.key)}" aria-expanded="${expanded}" aria-label="${expanded ? "收起" : "展开"}${escapeHtml(meta.label)}">${expanded ? "−" : "+"}</button>`
    : '<span class="tree-toggle-placeholder" aria-hidden="true"></span>';
  return `
    <span class="tree-cell" style="--tree-depth: ${meta.depth}">
      ${control}
      <span class="tree-label">${escapeHtml(meta.label)}</span>
    </span>
  `;
}

function renderTabs() {
  const previousTableWrap = document.querySelector("#tab-body .table-wrap");
  const previousTableScroll = {
    left: previousTableWrap?.scrollLeft || 0,
    top: previousTableWrap?.scrollTop || 0
  };
  const previousTableKey = dashboardState.renderedTableKey;
  const previousPageScroll = { left: window.scrollX, top: window.scrollY };
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
  const currentTableKey = `${dashboardState.data?.meta?.period_key || "-"}:${current.id || "-"}`;
  const highlights = current.highlights || [];
  const rows = current.rows || [];
  const columns = current.columns || [];
  const currentSort = dashboardState.sorts[current.id] || null;
  const sortColumn = currentSort ? columns.find((column) => column.key === currentSort.key) : null;
  const dimensionField = current.dimension_field;
  const dimensionOptions = dimensionField
    ? [...new Set(rows.map((row) => row[dimensionField]).filter(Boolean))]
    : [];
  const activeDimension = dashboardState.dimensions[current.id] || dimensionOptions[0] || "";
  const dimensionRows = activeDimension
    ? rows.filter((row) => row[dimensionField] === activeDimension)
    : rows;
  const trafficTree = current.id === "traffic"
    ? buildTrafficTree(dimensionRows, sortColumn, currentSort?.direction)
    : null;
  const displayRows = trafficTree
    ? trafficTree.rows
    : sortRows(dimensionRows, sortColumn, currentSort?.direction);

  document.querySelector("#tab-body").innerHTML = `
    <h3>${escapeHtml(current.headline || "-")}</h3>
    <section class="tab-section">
      <p class="section-title">优势与劣势</p>
      <div class="insight-grid">
        ${highlights.map((item) => `
          <article class="insight-card ${item.status === "warning" ? "warning" : "advantage"}">
            <div class="insight-card-label">
              <p class="insight-type">${item.status === "warning" ? "劣势" : "优势"}</p>
              <h4>${escapeHtml(item.label || "-")}</h4>
            </div>
            <div class="insight-compare ${item.status === "warning" ? "warning" : "advantage"}">
              <span>${escapeHtml(formatHighlightGap(item))}</span>
              <span class="insight-compare-divider" aria-hidden="true"></span>
              <span>${escapeHtml(formatHighlightRatio(item))}</span>
            </div>
          </article>
        `).join("") || '<p class="empty-inline">当前周期暂无重点数据</p>'}
      </div>
    </section>
    <section class="tab-section">
      <div class="table-tools">
        <p class="section-title">完整数据对比</p>
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
        <table class="data-table data-table-${escapeHtml(current.id || "default")}">
          <thead><tr>${columns.map((column) => {
            const active = currentSort?.key === column.key;
            const direction = active ? currentSort.direction : "";
            const ariaSort = direction === "desc" ? "descending" : direction === "asc" ? "ascending" : "none";
            return `<th aria-sort="${ariaSort}">
              <button class="sort-button ${active ? "active" : ""}" type="button" data-sort-key="${escapeHtml(column.key)}">
                <span>${escapeHtml(column.label)}</span>
                ${active ? `<span class="sort-arrow" aria-hidden="true">${direction === "desc" ? "↓" : "↑"}</span>` : ""}
              </button>
            </th>`;
          }).join("")}</tr></thead>
          <tbody>
            ${displayRows.map((row) => `
              <tr class="${trafficTree ? "tree-row" : ""}">${columns.map((column, columnIndex) => `
                <td>${trafficTree && column.key === "path"
                  ? renderTrafficTreeCell(row, trafficTree)
                  : columnIndex === 0 && ["keywords", "customer_profile"].includes(current.id)
                    ? renderFrozenTextCell(row, column)
                    : renderCell(row, column)}</td>
              `).join("")}</tr>
            `).join("") || `<tr><td class="empty-cell" colspan="${Math.max(columns.length, 1)}">没有符合条件的数据</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
    ${(current.notes || []).length ? `<ul class="notes">${current.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>` : ""}
  `;
  dashboardState.renderedTableKey = currentTableKey;
  if (previousTableKey === currentTableKey) {
    const currentTableWrap = document.querySelector("#tab-body .table-wrap");
    if (currentTableWrap) {
      currentTableWrap.scrollLeft = previousTableScroll.left;
      currentTableWrap.scrollTop = previousTableScroll.top;
    }
    window.scrollTo(previousPageScroll.left, previousPageScroll.top);
  }

  document.querySelectorAll("[data-dimension]").forEach((button) => {
    button.addEventListener("click", () => {
      dashboardState.dimensions[current.id] = button.dataset.dimension;
      renderTabs();
    });
  });
  document.querySelectorAll("[data-sort-key]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sortKey;
      const previous = dashboardState.sorts[current.id];
      if (!previous || previous.key !== key) {
        dashboardState.sorts[current.id] = { key, direction: "desc" };
      } else if (previous.direction === "desc") {
        dashboardState.sorts[current.id] = { key, direction: "asc" };
      } else {
        delete dashboardState.sorts[current.id];
      }
      renderTabs();
      document.querySelector(`[data-sort-key="${CSS.escape(key)}"]`)?.focus({ preventScroll: true });
    });
  });
  document.querySelectorAll("[data-traffic-tree-key]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.trafficTreeKey;
      if (dashboardState.expandedTrafficPaths.has(key)) {
        dashboardState.expandedTrafficPaths.delete(key);
      } else {
        dashboardState.expandedTrafficPaths.add(key);
      }
      renderTabs();
      const restoredToggle = [...document.querySelectorAll("[data-traffic-tree-key]")]
        .find((item) => item.dataset.trafficTreeKey === key);
      restoredToggle?.focus({ preventScroll: true });
    });
  });
  document.querySelectorAll(".frozen-cell-tip").forEach((tip) => {
    tip.addEventListener("click", () => tip.classList.toggle("show-tooltip"));
    tip.addEventListener("blur", () => tip.classList.remove("show-tooltip"));
  });
}

function renderDiagnosis() {
  const target = document.querySelector("#diagnosis");
  const tabs = dashboardState.data?.tabs || [];
  const primarySuggestions = [];
  const secondarySuggestions = [];
  tabs.forEach((tab) => {
    const highlights = [...(tab.highlights || [])].sort((left, right) =>
      Number(right.status === "warning") - Number(left.status === "warning")
    );
    const suggestions = highlights.map((item) => ({ ...item, sourceLabel: tab.label || "差距来源" }));
    if (suggestions[0]) {
      primarySuggestions.push(suggestions[0]);
    }
    secondarySuggestions.push(...suggestions.slice(1));
  });
  const suggestions = [...primarySuggestions, ...secondarySuggestions].slice(0, 5);
  target.innerHTML = suggestions.map((item) => `
    <section class="diagnosis-card ${item.status === "warning" ? "warning" : "advantage"}">
      <p class="diagnosis-type">${escapeHtml(item.sourceLabel)} · ${item.status === "warning" ? "劣势" : "优势"}</p>
      <h3>${escapeHtml(item.action || "持续跟踪当前差距并验证优化效果")}</h3>
      <p class="diagnosis-context">关注：${escapeHtml(item.label || "-")}</p>
    </section>
  `).join("") || '<p class="empty-inline">当前周期暂无行动建议</p>';
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
 * 返回值：无；直接更新趋势标题、范围说明和 ECharts 图表。
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
  document.querySelector("#trend-scope").textContent = `${scopeLabels[granularity] || `${series.length} 个周期`} · 点击指标卡切换`;
  const target = document.querySelector("#trend-chart");
  disposeTrendChart();
  target.innerHTML = "";
  target.setAttribute("aria-label", `${metric.label || "指标"}本品与竞品趋势图`);
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
        data: series.map((item) => item.selfValue)
      },
      {
        name: "竞品",
        type: "line",
        smooth: 0.35,
        symbol: "circle",
        symbolSize: 7,
        showSymbol: true,
        lineStyle: { width: 3 },
        data: series.map((item) => item.competitorValue)
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
    meta.granularity ? `分析粒度：${granularityLabels[meta.granularity] || meta.granularity}` : "",
    meta.self_spu ? `本品 SPU ${meta.self_spu}` : "",
    meta.competitor_spu ? `竞品 SPU ${meta.competitor_spu}` : ""
  ].filter(Boolean).join(" | ");
  const summary = meta.summary || "-";
  const weakness = meta.weakness_summary || "-";
  document.querySelector("#summary").textContent = summary;
  document.querySelector("#summary").title = summary;
  document.querySelector("#weakness").textContent = weakness;
  document.querySelector("#weakness").title = weakness;
  const metricItems = data.core_metrics || [];
  const preferredMetricId = activeMetricId || dashboardState.activeMetricId;
  dashboardState.activeMetricId = metricItems.some((item) => item.id === preferredMetricId)
    ? preferredMetricId
    : metricItems[0]?.id || "";
  const metrics = document.querySelector("#metrics");
  metrics.innerHTML = metricItems.map((item) => {
    const selfText = formatValue(item.self_value, item.unit);
    const competitorText = formatValue(item.competitor_value, item.unit);
    const statusClass = item.status === "warning" ? "warning" : "advantage";
    return `
      <button class="metric-card status-${statusClass} ${item.id === dashboardState.activeMetricId ? "active" : ""}" type="button" data-metric-id="${escapeHtml(item.id)}" aria-pressed="${item.id === dashboardState.activeMetricId}">
        <div class="metric-card-head">
          <p class="metric-title">${escapeHtml(item.label || "-")}</p>
          <div class="metric-gap">
            <span>${escapeHtml(formatMetricGap(item))}</span>
            <span class="metric-gap-divider" aria-hidden="true"></span>
            <span>${escapeHtml(formatMetricRatio(item))}</span>
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
