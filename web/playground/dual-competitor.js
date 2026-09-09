import * as echarts from "echarts";

const $ = (selector) => document.querySelector(selector);
const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const state = { product: 0, mode: "dual", date: "", metric: "amount", table: "traffic" };
let data;
let tables;
let chart;
const colors = ["#0f7b73", "#b96905", "#6076a3"];
const classes = ["", "a", "b"];
const roles = ["本品", "竞品 A", "竞品 B"];
const formatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });

function product() { return data.products[state.product]; }
function competitors() { return product().competitors.slice(0, state.mode === "single" ? 1 : 2); }
function available(item, index) {
  return index === 0 || !((state.mode === "missing" && index === 2) || item.missingDates?.includes(state.date));
}
function number(value, metric) {
  if (value === null || value === undefined) return "—";
  if (metric.unit === "%") return `${value.toFixed(metric.decimals)}%`;
  return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 0, maximumFractionDigits: metric.decimals }).format(value);
}
function gap(value, other, percent = false) {
  if (value == null || other == null) return { text: "—", kind: "neutral" };
  const difference = value - other;
  if (!difference) return { text: "持平", kind: "neutral" };
  if (!percent && other === 0) return { text: `${difference > 0 ? "+" : "−"}${formatter.format(Math.abs(difference))}`, kind: difference > 0 ? "up" : "down" };
  const amount = percent ? Math.abs(difference) : Math.abs(difference / other * 100);
  return { text: `${difference > 0 ? "+" : "−"}${amount.toFixed(1)}${percent ? " pct" : "%"}`, kind: difference > 0 ? "up" : "down" };
}

/**
 * 功能说明：渲染本品和全部对照竞品，共用一个日期，主图独立跳转京东。
 * 参数：无，读取页面 state 与外部演示商品配置 data。
 * 返回值：无，更新商品、周期说明与布局列数。
 */
function renderProducts() {
  const items = [product(), ...competitors()];
  document.documentElement.style.setProperty("--product-count", items.length);
  document.documentElement.style.setProperty("--competitor-count", items.length - 1);
  $("#products").innerHTML = items.map((item, i) => `<article class="product">
    <a class="photo-link" href="https://item.jd.com/${encodeURIComponent(item.id)}.html" target="_blank" rel="noopener noreferrer" aria-label="打开${escape(item.name)}的京东详情（新窗口）"><img src="${escape(item.image)}" alt="${escape(item.name)}主图"></a>
    <div class="product-copy"><div class="identity"><span class="badge ${classes[i]}">${roles[i]}</span>${!available(item, i) ? '<span class="subtle">暂无报告</span>' : ""}</div>
      ${i === 0 ? `<select id="product-select" aria-label="切换本品">${data.products.map((p, j) => `<option value="${j}" ${j === state.product ? "selected" : ""}>${escape(p.name)}</option>`).join("")}</select>` : `<p class="product-name" title="${escape(item.name)}">${escape(item.name)}</p>`}
      <p class="product-id">商品 ID ${escape(item.id)}</p></div></article>`).join("");
  $("#product-select").onchange = (event) => {
    state.product = Number(event.target.value);
    render();
    $("#product-select").focus();
  };
  $("#products").querySelectorAll("img").forEach((img) => {
    img.onerror = () => { img.parentElement.textContent = "暂无主图"; };
  });
  $("#period-note").textContent = `${state.date} · ${items.length - 1} 个竞品同屏对照`;
}

function renderSummaries() {
  $("#summaries").innerHTML = competitors().map((item, i) => available(item, i + 1)
    ? `<button class="summary" data-detail="${i}" aria-haspopup="dialog" aria-controls="detail" aria-label="查看本品对比${escape(item.name)}的优缺点详情">
      <span class="summary-header"><i class="dot ${classes[i + 1]}"></i>对比 ${escape(item.shortName)}</span>
      <span class="summary-line weak"><span>弱点</span><strong>${escape(item.weakness)}</strong></span>
      <span class="summary-line strong"><span>优点</span><strong>${escape(item.strength)}</strong></span></button>`
    : `<div class="summary is-missing"><p class="summary-header"><i class="dot ${classes[i + 1]}"></i>对比 ${escape(item.shortName)}</p><p class="missing-copy">${state.date} 暂无报告</p></div>`).join("");
}

function renderMetrics() {
  const items = [product(), ...competitors()];
  $("#metrics").innerHTML = data.metrics.map((metric) => `<button class="metric" data-metric="${metric.key}" aria-pressed="${state.metric === metric.key}" aria-label="查看${metric.label}三方趋势">
    <span class="metric-header"><b>${metric.label}</b><span>${metric.unit}</span></span>
    <span class="metric-values">${items.map((item, i) => `<span class="metric-value"><small>${roles[i]}</small><strong>${available(item, i) ? number(item.metrics[metric.key], metric) : "—"}</strong></span>`).join("")}</span>
    <span class="metric-gaps">${competitors().map((item, i) => {
      const difference = gap(product().metrics[metric.key], available(item, i + 1) ? item.metrics[metric.key] : null, metric.unit === "%");
      return `<span class="${difference.kind}">较 ${String.fromCharCode(65 + i)} ${difference.text}</span>`;
    }).join("")}</span></button>`).join("");
}

/**
 * 功能说明：在同一坐标系展示三方七天趋势，缺失日期保持断点。
 * 参数：无，读取 state 的日期、指标及外部示例数据。
 * 返回值：无，更新图表及可访问的趋势说明。
 */
function renderTrend() {
  const metric = data.metrics.find((item) => item.key === state.metric);
  const items = [product(), ...competitors()];
  const dates = Array.from({ length: 7 }, (_, i) => {
    const day = new Date(`${state.date}T00:00:00Z`);
    day.setUTCDate(day.getUTCDate() - 6 + i);
    return day.toISOString().slice(0, 10);
  });
  $("#trend-title").textContent = `${metric.label}趋势`;
  $("#trend").setAttribute("aria-label", `${dates[0]} 至 ${state.date}，${items.map((p) => p.name).join("、")}的${metric.label}趋势，数值可在图上查看`);
  $("#legend").innerHTML = items.map((item, i) => `<span><i class="dot ${classes[i]}"></i>${roles[i]} · ${escape(item.shortName || item.name)}</span>`).join("");
  $("#chart-note").textContent = items.some((p, i) => i && !available(p, i))
    ? "所选日期缺失的竞品显示为空，其他日期仍展示已有趋势。"
    : "点击上方指标切换趋势 · 实线为本品，虚线为竞品估算值";
  chart.setOption({
    animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    animationDuration: 200,
    color: colors,
    grid: { top: 18, left: 8, right: 12, bottom: 10, containLabel: true },
    tooltip: { trigger: "axis", confine: true, backgroundColor: "#fffdf8", borderColor: "#ded6c8", textStyle: { color: "#1f2933", fontSize: 12 }, valueFormatter: (value) => number(value, metric) },
    xAxis: { type: "category", boundaryGap: false, data: dates.map((d) => d.slice(5)), axisLine: { lineStyle: { color: "#ded6c8" } }, axisTick: { show: false }, axisLabel: { color: "#667085", fontSize: 11, margin: 16 } },
    yAxis: { type: "value", axisLabel: { color: "#667085", fontSize: 11, formatter: (value) => metric.unit === "%" ? `${value}%` : value >= 1000 ? `${value / 1000}k` : value }, splitLine: { lineStyle: { color: "#ded6c8", type: "dashed" } } },
    series: items.map((item, i) => ({
      name: `${roles[i]} · ${item.shortName || item.name}`, type: "line", smooth: .25, connectNulls: false,
      symbol: ["circle", "diamond", "rect"][i], symbolSize: 7,
      lineStyle: { width: i ? 2 : 3, type: i ? "dashed" : "solid" },
      data: dates.map((day, j) => (item.missingDates?.includes(day) || (j === 6 && !available(item, i))) ? null : Number((item.metrics[metric.key] * item.trend[j]).toFixed(metric.decimals)))
    }))
  }, true);
}

/**
 * 功能说明：按维度生成三方并列表格，分别计算本品与每个竞品的差距。
 * 参数：无，读取外部 tables 配置和当前商品、日期状态。
 * 返回值：无，更新表头、表格数据和单位说明。
 */
function renderTable() {
  const definition = tables.find((item) => item.id === state.table);
  const items = [product(), ...competitors()];
  const isShare = definition.metric === "share";
  $("#table-unit").textContent = definition.unit;
  $("#tabs").querySelectorAll("button").forEach((button) => {
    const selected = button.dataset.table === state.table;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  $("#comparison-panel").setAttribute("aria-labelledby", `tab-${state.table}`);
  $("#comparison").innerHTML = `<thead><tr><th scope="col">${definition.dimension}</th><th scope="col" class="self-column">本品</th>${competitors().map((item, i) => `<th scope="col" class="group-start"><span class="badge ${classes[i + 1]}">${roles[i + 1]}</span> ${escape(item.shortName)}</th><th scope="col">本品较 ${String.fromCharCode(65 + i)}</th>`).join("")}</tr></thead><tbody>${definition.rows.map((row) => {
    const values = items.map((item, i) => !available(item, i) || row.values[i] == null ? null : isShare ? row.values[i] : Math.round(item.metrics.visitors * row.values[i]));
    const display = (value) => value == null ? "—" : isShare ? `${value.toFixed(1)}%` : formatter.format(value);
    return `<tr><th scope="row">${escape(row.name)}</th><td class="self-column">${display(values[0])}</td>${competitors().map((item, i) => {
      const difference = gap(values[0], values[i + 1], isShare);
      return `<td class="group-start">${display(values[i + 1])}</td><td class="${difference.kind}">${difference.text}</td>`;
    }).join("")}</tr>`;
  }).join("")}</tbody>`;
}

function renderAdvice() {
  $("#advice").innerHTML = competitors().map((item, i) => `<article class="panel advice ${classes[i + 1]}"><header><span class="badge ${classes[i + 1]}">${roles[i + 1]}</span><h3>对比 ${escape(item.shortName)}</h3></header>${available(item, i + 1)
    ? `<ol>${item.advice.map((a) => `<li><h3>${escape(a.title)}</h3><p>${escape(a.detail)}</p></li>`).join("")}</ol>`
    : `<p class="missing-copy">${state.date} 暂无报告</p>`}</article>`).join("");
}

function showDetail(index) {
  const item = competitors()[index];
  $("#detail-context").textContent = `本品对比 ${item.name}`;
  const list = (positive) => data.metrics.filter((metric) => positive ? product().metrics[metric.key] > item.metrics[metric.key] : product().metrics[metric.key] < item.metrics[metric.key])
    .map((metric) => `<li>${metric.label}：本品 ${number(product().metrics[metric.key], metric)}，竞品 ${number(item.metrics[metric.key], metric)}。</li>`).join("");
  $("#detail-content").innerHTML = `<section class="detail-section"><h3 class="weak">弱点 · ${escape(item.weakness)}</h3><ul>${list(false) || "<li>暂无落后的核心指标。</li>"}</ul></section><section class="detail-section"><h3 class="strong">优点 · ${escape(item.strength)}</h3><ul>${list(true) || "<li>暂无领先的核心指标。</li>"}</ul></section>`;
  $("#detail").showModal();
}

function render() {
  renderProducts();
  renderSummaries();
  renderMetrics();
  renderTrend();
  renderTable();
  renderAdvice();
}

/**
 * 功能说明：加载独立演示配置并绑定交互；此流程不请求业务 API。
 * 参数：无。
 * 返回值：初始化完成的 Promise；失败时在页面展示错误。
 */
async function initialize() {
  console.info("双竞品预览开始加载示例配置");
  const [productsResponse, tablesResponse] = await Promise.all([fetch("./multi-competitor-data.json"), fetch("./dual-competitor-tables.json")]);
  if (!productsResponse.ok || !tablesResponse.ok) throw new Error("示例配置加载失败，请刷新页面重试");
  data = await productsResponse.json();
  tables = (await tablesResponse.json()).tables;
  state.date = data.dates[0];
  $("#report-date").innerHTML = data.dates.map((date) => `<option value="${date}">${date.replaceAll("-", " / ")}</option>`).join("");
  $("#report-date").onchange = (event) => { state.date = event.target.value; render(); };
  $("#tabs").innerHTML = tables.map((table) => `<button role="tab" id="tab-${table.id}" data-table="${table.id}" aria-controls="comparison-panel">${table.label}</button>`).join("");
  $("#tabs").onclick = (event) => {
    const button = event.target.closest("[data-table]");
    if (button) { state.table = button.dataset.table; renderTable(); }
  };
  $("#tabs").onkeydown = (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = tables.findIndex((item) => item.id === state.table);
    const index = event.key === "Home" ? 0 : event.key === "End" ? tables.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + tables.length) % tables.length;
    state.table = tables[index].id;
    renderTable();
    $(`#tab-${state.table}`).focus();
  };
  document.querySelectorAll("[data-mode]").forEach((button) => button.onclick = () => {
    state.mode = button.dataset.mode;
    document.querySelectorAll("[data-mode]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    render();
  });
  $("#metrics").onclick = (event) => {
    const button = event.target.closest("[data-metric]");
    if (!button) return;
    state.metric = button.dataset.metric;
    renderMetrics();
    renderTrend();
    $(`[data-metric="${state.metric}"]`).focus();
  };
  $("#summaries").onclick = (event) => {
    const button = event.target.closest("[data-detail]");
    if (button) showDetail(Number(button.dataset.detail));
  };
  $("#close-detail").onclick = () => $("#detail").close();
  $("#detail").onclick = (event) => { if (event.target === $("#detail")) {
    const bounds = event.target.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.target.close();
  } };
  $("#dashboard").hidden = false;
  chart = echarts.init($("#trend"));
  new ResizeObserver(() => chart.resize()).observe($("#trend"));
  render();
  console.info("双竞品预览加载完成", { products: data.products.length, tables: tables.length });
}

initialize().catch((error) => {
  console.error("双竞品预览加载失败", error);
  $("#error").hidden = false;
  $("#error").textContent = error.message;
});
