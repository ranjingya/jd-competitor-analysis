import { compareValues, formatValue } from "./compact-table-model.js";

const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

/**
 * 功能说明：渲染差距前置预览，竞品差距纵向排列，三方原始值按商品分组置于右侧。
 * 参数 source：包含指标定义与示例行的数据；competitorCount：展示的竞品数量。
 * 返回值：无，将语义表格写入预览区域。
 */
function render(source, competitorCount) {
  const metrics = source.metrics;
  // 小块预览展示前三个示例渠道，覆盖领先、落后和缺失值。
  const rows = source.rows.slice(0, 3);
  const products = Array.from({ length: competitorCount + 1 }, (_, index) => index === 0 ? "本品" : `竞品 ${index}`);
  const label = (metric) => `${escape(metric.label)}${metric.unit === "元" ? "（元）" : ""}`;
  document.querySelector("#preview").innerHTML = `<table style="width:${260 + metrics.length * 154 + products.length * metrics.length * 120}px">
    <caption>左侧两行分别为本品较竞品 1、竞品 2 的差距；右侧按商品分组展示原始值</caption>
    <colgroup><col class="channel-col"><col class="role-col">${metrics.map(() => '<col class="gap-col">').join("")}${products.map(() => metrics.map(() => '<col class="raw-col">').join("")).join("")}</colgroup>
    <thead>
      <tr><th rowspan="2" class="channel">${escape(source.dimension)}</th><th rowspan="2" class="role">对比</th><th colspan="${metrics.length}" class="group-heading">本品差距</th>${products.map((product, index) => `<th colspan="${metrics.length}" class="raw-heading group-heading"${index === 0 ? ' id="raw-start"' : ""}>${product} · 原始值</th>`).join("")}</tr>
      <tr>${metrics.map((metric, index) => `<th id="gap-${index}">${label(metric)}</th>`).join("")}${products.map((product, productIndex) => metrics.map((metric, index) => `<th id="raw-${productIndex}-${index}" class="raw-heading${index === 0 ? " group-start" : ""}"><span class="sr-only">${product}</span>${label(metric)}</th>`).join("")).join("")}</tr>
    </thead>
    <tbody>${rows.map((row, rowIndex) => `<tr>
      <th id="channel-${rowIndex}" class="channel" scope="row">${escape(row.name)}<small>${escape(row.parent)}</small></th>
      <td class="role">${products.slice(1).map((product) => `<div class="compare-line">${product}</div>`).join("")}</td>
      ${metrics.map((metric, metricIndex) => `<td headers="channel-${rowIndex} gap-${metricIndex}">${products.slice(1).map((product, index) => {
        const values = row.values[metric.key];
        const delta = compareValues(values[0], values[index + 1], metric.unit);
        return `<div class="compare-line ${delta.tone}"><span class="sr-only">较${product}：</span><strong>${escape(delta.primary)}</strong>${delta.primary !== "—" && delta.secondary ? `<small>${escape(delta.secondary)}</small>` : ""}</div>`;
      }).join("")}</td>`).join("")}
      ${products.map((_, productIndex) => metrics.map((metric, metricIndex) => `<td headers="channel-${rowIndex} raw-${productIndex}-${metricIndex}" class="${metricIndex === 0 ? "group-start" : ""}">${formatValue(row.values[metric.key][productIndex], metric.unit)}</td>`).join("")).join("")}
    </tr>`).join("")}</tbody></table>`;
  document.querySelector("#preview").scrollLeft = 0;
}

/**
 * 功能说明：读取本地预览配置，并绑定单/双竞品切换。
 * 参数：无。
 * 返回值：Promise，失败时显示加载错误，不访问业务 API。
 */
async function initialize() {
  console.info("紧凑数值样式预览开始加载");
  const response = await fetch("./compact-table-data.json");
  if (!response.ok) throw new Error("预览数据加载失败，请刷新重试");
  const { tables } = await response.json();
  const source = tables[0];
  render(source, 2);
  document.querySelector("#show-raw").onclick = () => {
    const host = document.querySelector("#preview");
    const target = document.querySelector("#raw-start");
    host.scrollLeft += target.getBoundingClientRect().left - host.getBoundingClientRect().left - 260;
  };
  document.querySelector("#show-gaps").onclick = () => { document.querySelector("#preview").scrollLeft = 0; };
  document.querySelectorAll("[data-count]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-count]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      render(source, Number(button.dataset.count));
    });
  });
  console.info("紧凑数值样式预览加载完成");
}

initialize().catch((error) => {
  console.error("紧凑数值样式预览加载失败", error);
  const target = document.querySelector("#error");
  target.hidden = false;
  target.textContent = error.message;
});
