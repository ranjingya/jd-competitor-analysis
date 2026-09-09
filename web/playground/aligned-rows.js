import { compareValues, formatValue } from "./compact-table-model.js";

const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

/** 根据原始占比绘制进度条，缺失值保留为空。 */
function progress(value) {
  if (!Number.isFinite(value)) return '<span class="neutral">—</span>';
  return `<span class="bar-value"><span class="track" aria-hidden="true"><span class="fill" style="width:${Math.max(0, Math.min(100, value))}%"></span></span><strong>${formatValue(value, "%")}</strong></span>`;
}

/**
 * 功能说明：用真实表格行展示商品身份，以跨行单元格展示渠道与右侧原值。
 * 参数 source：外部示例渠道配置；count：竞品数量。
 * 返回值：无，更新独立预览，不修改正式看板。
 */
function render(source, count) {
  const peers = Array.from({ length: count }, (_, i) => i + 1);
  document.querySelector("#preview").innerHTML = `<table><colgroup><col style="width:170px"><col style="width:72px"><col style="width:94px"><col style="width:258px"><col style="width:170px">${peers.map(() => '<col style="width:120px">').join("")}</colgroup>
    <thead><tr><th class="plain" rowspan="2">渠道</th><th class="plain" rowspan="2">对比</th><th class="edge" colspan="3">差距</th>${peers.map((i) => `<th class="plain edge">竞品 ${i}</th>`).join("")}</tr><tr><th class="edge">判断</th><th class="metric-edge">总访客占比</th><th class="metric-edge">访客</th>${peers.map(() => '<th class="plain edge">访客</th>').join("")}</tr></thead>
    ${source.rows.slice(0, 3).map((row) => `<tbody>${[0, ...peers].map((i) => {
      const visitors = row.values.visitors;
      const share = row.values.total_share;
      const delta = compareValues(visitors[0], visitors[i], "人");
      const shareDelta = compareValues(share[0], share[i], "%");
      const judgement = delta.primary === "—" ? "—" : visitors[0] > visitors[i] ? "领先" : visitors[0] < visitors[i] ? "落后" : "持平";
      return `<tr>${i === 0 ? `<th class="channel" scope="rowgroup" rowspan="${count + 1}">${escape(row.name)}<small>${escape(row.parent)}</small></th>` : ""}<th scope="row" class="role ${i === 0 ? "self" : ""}">${i === 0 ? "本品" : `竞品 ${i}`}</th>
      <td class="edge ${i === 0 ? "" : delta.tone}">${i === 0 ? "" : judgement}</td>
      <td class="metric-edge"><div class="share">${progress(share[i])}<strong class="${shareDelta.tone}">${i === 0 ? "" : escape(shareDelta.primary)}</strong></div></td>
      <td class="metric-edge">${i === 0 ? `<div class="number">${formatValue(visitors[0], "人")}</div>` : `<div class="delta ${delta.tone}"><strong>${escape(delta.primary)}</strong><small>${escape(delta.secondary || "")}</small></div>`}</td>
      ${i === 0 ? peers.map((peer) => `<td class="edge merged" rowspan="${count + 1}">${formatValue(visitors[peer], "人")}</td>`).join("") : ""}</tr>`;
    }).join("")}</tbody>`).join("")}</table>`;
}

/** 加载本地演示配置并绑定竞品数量切换，返回初始化 Promise。 */
async function initialize() {
  console.info("合并行预览加载开始");
  const response = await fetch("./compact-table-data.json");
  if (!response.ok) throw new Error("示例数据加载失败");
  const { tables } = await response.json();
  render(tables[0], 2);
  document.querySelectorAll("[data-count]").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("[data-count]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    render(tables[0], Number(button.dataset.count));
  }));
  console.info("合并行预览加载完成");
}
initialize().catch((error) => { console.error(error); document.querySelector("#preview").textContent = error.message; });
