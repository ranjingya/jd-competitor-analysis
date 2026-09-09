import { compareValues, formatValue } from "./compact-table-model.js";

const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

/**
 * 功能说明：渲染小块三方数值预览，身份统一显示在左侧，指标格只展示数值与差距。
 * 参数 source：包含指标定义与示例行的数据；competitorCount：展示的竞品数量。
 * 返回值：无，将语义表格写入预览区域。
 */
function render(source, competitorCount) {
  const metrics = source.metrics;
  // 小块预览展示前三个示例渠道，覆盖领先、落后和缺失值。
  const rows = source.rows.slice(0, 3);
  document.querySelector("#preview").innerHTML = `<table>
    <caption>每个渠道按本品、竞品 1、竞品 2 纵向排列；彩色数字表示本品相对该竞品的差距</caption>
    <colgroup><col class="channel-col"><col class="role-col">${metrics.map(() => "<col>").join("")}</colgroup>
    <thead><tr><th colspan="2" scope="col">${escape(source.dimension)}</th>${metrics.map((metric, metricIndex) => `<th id="metric-${metricIndex}" scope="col">${escape(metric.label)}${metric.unit === "元" ? "（元）" : ""}</th>`).join("")}</tr></thead>
    ${rows.map((row, rowIndex) => `<tbody>${Array.from({ length: competitorCount + 1 }, (_, index) => {
      const role = index === 0 ? "本品" : `竞品 ${index}`;
      return `<tr class="${index === 0 ? "self-row" : "competitor-row"}">
        ${index === 0 ? `<th id="channel-${rowIndex}" class="channel" scope="rowgroup" rowspan="${competitorCount + 1}">${escape(row.name)}<small>${escape(row.parent)}</small></th>` : ""}
        <th id="role-${rowIndex}-${index}" class="role" scope="row">${role}</th>
        ${metrics.map((metric, metricIndex) => {
          const values = row.values[metric.key];
          const delta = compareValues(values[0], values[index], metric.unit);
          const difference = delta.primary === "—" ? "—" : `${delta.primary}${delta.secondary ? ` · ${delta.secondary}` : ""}`;
          return `<td headers="channel-${rowIndex} role-${rowIndex}-${index} metric-${metricIndex}"><span class="value">${formatValue(values[index], metric.unit)}</span>${index === 0 ? "" : `<span class="gap ${delta.tone}${delta.primary === "—" ? " is-empty" : ""}">${escape(difference)}</span>`}</td>`;
        }).join("")}</tr>`;
    }).join("")}</tbody>`).join("")}</table>`;
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
