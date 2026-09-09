import { compareValues, formatValue, sceneValues } from "./compact-table-model.js";

const $ = (selector) => document.querySelector(selector);
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const state = { layout: "rows", scene: "dual", dimension: "traffic", metric: "all", search: "", expanded: new Set() };
let tables = [];
const table = () => tables.find((item) => item.id === state.dimension);
const count = () => state.scene === "single" ? 1 : 2;
const selectedMetrics = () => table().metrics.filter((metric) => state.metric === "all" || metric.key === state.metric);
const role = (index) => index === 0 ? "本品" : `竞品 ${index}`;
const values = (row, metric) => sceneValues(row.values[metric.key], state.scene);

function deltaMarkup(self, competitor, metric, inline = false) {
  const delta = compareValues(self, competitor, metric.unit);
  if (inline) return `<span class="inline-delta ${delta.tone}">差 ${escape(delta.primary)}${delta.secondary ? ` · ${escape(delta.secondary)}` : ""}</span>`;
  return `<span class="delta ${delta.tone}"><b>${escape(delta.primary)}</b>${delta.secondary ? `<small>${escape(delta.secondary)}</small>` : ""}</span>`;
}

function nameMarkup(row, expandable = false) {
  const text = escape(row.name);
  return `${expandable ? `<button type="button" class="detail-toggle" data-row="${escape(row.id)}" aria-expanded="${state.expanded.has(row.id)}" aria-label="${state.expanded.has(row.id) ? "收起" : "展开"}${text}的三方完整数值">${text}</button>` : text}${row.parent ? `<small>${escape(row.parent)}</small>` : ""}`;
}

/**
 * 功能说明：构建纵向指标表，每项指标都直接展示双方差距与三方原始值。
 * 参数 rows：筛选后的对象；metrics：当前选择的指标定义。
 * 返回值：具有语义表头和合并对象单元格的 HTML。
 */
function rowsTable(rows, metrics) {
  return `<table><caption>指标纵排：先看差距，再看三方数值</caption><colgroup><col class="object-col"><col class="metric-col">${Array(2 * count() + 1).fill("<col>").join("")}</colgroup>
    <thead><tr><th scope="col">${escape(table().dimension)}</th><th scope="col">指标</th>${Array.from({ length: count() }, (_, i) => `<th class="derived" scope="col">较竞品 ${i + 1}</th>`).join("")}<th scope="col">本品</th>${Array.from({ length: count() }, (_, i) => `<th scope="col">竞品 ${i + 1}</th>`).join("")}</tr></thead>
    ${rows.map((row, index) => `<tbody>${metrics.map((metric, mi) => {
      const items = values(row, metric);
      return `<tr class="${index % 2 ? "row-stripe" : ""}">${mi === 0 ? `<th scope="rowgroup" rowspan="${metrics.length}" class="object-cell">${nameMarkup(row)}</th>` : ""}<th scope="row">${escape(metric.label)}<span class="unit">${metric.unit}</span></th>${items.slice(1).map((value) => `<td>${deltaMarkup(items[0], value, metric)}</td>`).join("")}${items.map((value, i) => `<td class="${i === 0 ? "self-value" : ""}">${formatValue(value, metric.unit)}</td>`).join("")}</tr>`;
    }).join("")}</tbody>`).join("")}</table>`;
}

function rawDetail(row) {
  return `<h3>${escape(row.name)} · 三方完整数值</h3><table><thead><tr><th scope="col">指标</th>${Array.from({ length: count() + 1 }, (_, i) => `<th scope="col">${role(i)}</th>`).join("")}</tr></thead><tbody>${table().metrics.map((metric) => `<tr><th scope="row">${escape(metric.label)}<span class="unit">${metric.unit}</span></th>${values(row, metric).map((value) => `<td>${formatValue(value, metric.unit)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

/**
 * 功能说明：构建三方同格或差距优先矩阵，隐藏的原始值通过对象展开读取。
 * 参数 rows：筛选后的对象；metrics：选中的指标；gapsOnly：是否仅显示差距。
 * 返回值：矩阵 HTML，差距优先模式支持展开该对象全部指标。
 */
function matrixTable(rows, metrics, gapsOnly) {
  return `<table class="matrix-table"><caption>${gapsOnly ? "两组差距并列，展开对象可看三方原始值" : "每个指标格内三方上下对照"}</caption><colgroup><col class="object-col">${metrics.map(() => "<col>").join("")}</colgroup><thead><tr><th scope="col">${escape(table().dimension)}</th>${metrics.map((metric) => `<th scope="col" class="derived">${escape(metric.label)}<span class="unit">${metric.unit}</span></th>`).join("")}</tr></thead><tbody>${rows.map((row, index) => `<tr class="object-start ${index % 2 ? "row-stripe" : ""}"><th scope="row" class="object-cell">${nameMarkup(row, gapsOnly)}</th>${metrics.map((metric) => {
    const items = values(row, metric);
    return `<td>${gapsOnly ? `<div class="gap-pair">${items.slice(1).map((value, i) => `<div class="gap-line"><span>竞品 ${i + 1}</span>${deltaMarkup(items[0], value, metric)}</div>`).join("")}</div>` : `<div class="triple">${items.map((value, i) => `<div class="triple-line"><span>${role(i)}</span><strong class="${i === 0 ? "self-value" : ""}">${formatValue(value, metric.unit)}</strong>${i > 0 ? deltaMarkup(items[0], value, metric, true) : ""}</div>`).join("")}</div>`}</td>`;
  }).join("")}</tr>${gapsOnly && state.expanded.has(row.id) ? `<tr class="detail-row"><td colspan="${metrics.length + 1}">${rawDetail(row)}</td></tr>` : ""}`).join("")}</tbody></table>`;
}

/**
 * 功能说明：按布局、指标和场景渲染预览，所有对象均保留，不挑选重点行。
 * 参数：无，使用 state 与示例配置 tables。
 * 返回值：无，更新常规表格或正在打开的放大窗口。
 */
function renderTable() {
  const rows = table().rows.filter((row) => `${row.name} ${row.parent}`.includes(state.search.trim()));
  const metrics = selectedMetrics();
  $("#scope").textContent = `${rows.length} 项 · ${metrics.length} 个指标${state.scene === "missing" ? " · 竞品 2 暂无报告" : ""}`;
  const content = `<div class="table-scroll" tabindex="0" aria-label="${escape(table().label)}数据表格，可在表格内滚动">${!rows.length ? '<p class="empty">没有匹配的数据</p>' : state.layout === "rows" ? rowsTable(rows, metrics) : matrixTable(rows, metrics, state.layout === "gaps")}</div>`;
  $("#table-host").innerHTML = content;
  if ($("#full").open) $("#full-content").innerHTML = content;
}

function renderControls() {
  $("#dimensions").innerHTML = tables.map((item) => `<button type="button" data-dimension="${item.id}" aria-pressed="${state.dimension === item.id}">${escape(item.label)}</button>`).join("");
  $("#metrics").innerHTML = [{ key: "all", label: "全部" }, ...table().metrics].map((metric) => `<button type="button" data-metric="${metric.key}" aria-pressed="${state.metric === metric.key}">${escape(metric.label)}</button>`).join("");
  $("#table-title").textContent = `${table().label} · 完整数据对比`;
}

/**
 * 功能说明：加载独立示例并绑定布局切换、筛选、展开和放大交互，不调用业务 API。
 * 参数：无。
 * 返回值：Promise，加载异常由页面显示。
 */
async function initialize() {
  console.info("紧凑表格预览开始加载");
  const response = await fetch("./compact-table-data.json");
  if (!response.ok) throw new Error("示例数据加载失败，请刷新重试");
  tables = (await response.json()).tables;
  $("#panel").hidden = false;
  renderControls();
  renderTable();
  document.querySelectorAll("[data-layout]").forEach((button) => button.onclick = () => {
    state.layout = button.dataset.layout;
    document.querySelectorAll("[data-layout]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    renderTable();
  });
  $("#scene").onchange = (event) => { state.scene = event.target.value; renderTable(); };
  $("#search").oninput = (event) => { state.search = event.target.value; renderTable(); };
  $("#dimensions").onclick = (event) => {
    const button = event.target.closest("[data-dimension]");
    if (!button) return;
    state.dimension = button.dataset.dimension;
    state.metric = "all";
    state.search = "";
    state.expanded.clear();
    $("#search").value = "";
    renderControls(); renderTable();
    $(`[data-dimension="${state.dimension}"]`).focus({ preventScroll: true });
  };
  $("#metrics").onclick = (event) => {
    const button = event.target.closest("[data-metric]");
    if (!button) return;
    state.metric = button.dataset.metric;
    renderControls(); renderTable();
    $(`[data-metric="${state.metric}"]`).focus({ preventScroll: true });
  };
  for (const host of [$("#table-host"), $("#full-content")]) host.onclick = (event) => {
    const button = event.target.closest("[data-row]");
    if (!button) return;
    const id = button.dataset.row;
    state.expanded.has(id) ? state.expanded.delete(id) : state.expanded.add(id);
    const scrollTop = host.querySelector(".table-scroll").scrollTop;
    renderTable();
    host.querySelector(".table-scroll").scrollTop = scrollTop;
    [...host.querySelectorAll("[data-row]")].find((item) => item.dataset.row === id)?.focus({ preventScroll: true });
  };
  $("#expand").onclick = () => { $("#full").showModal(); renderTable(); };
  $("#close-full").onclick = () => $("#full").close();
  $("#full").onclick = (event) => {
    if (event.target !== $("#full")) return;
    const rect = event.target.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close();
  };
  console.info("紧凑表格预览加载完成", { tables: tables.length });
}

initialize().catch((error) => {
  console.error("紧凑表格预览加载失败", error);
  $("#error").hidden = false;
  $("#error").textContent = error.message;
});
