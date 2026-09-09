const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
let comparison;

/**
 * 功能说明：按相同比较方向归组指标，演示共同结论及有差异的结论；不合并竞品数值。
 * 参数：self 为本品；competitors 为带可用状态的竞品数组；metrics 为指标定义。
 * 返回值：各指标的逐竞品比较结果与按方向归组的指标。
 */
export function summarize({ self, competitors, metrics }) {
  const rows = metrics.map((metric) => ({
    metric,
    selfValue: self.metrics[metric.key],
    comparisons: competitors.map((item, index) => ({
      index,
      value: item.available ? item.metrics[metric.key] : null,
      direction: !item.available || !Number.isFinite(item.metrics[metric.key]) || !Number.isFinite(self.metrics[metric.key]) ? null : Math.sign(self.metrics[metric.key] - item.metrics[metric.key]),
    })),
  }));
  const groups = [];
  for (const row of rows) {
    const key = row.comparisons.map((item) => item.direction ?? "missing").join(",");
    const group = groups.find((item) => item.key === key);
    if (group) group.labels.push(row.metric.label);
    else groups.push({ key, labels: [row.metric.label], comparisons: row.comparisons });
  }
  return { rows, groups };
}

function target(items, total) {
  if (total > 1 && items.length === total) return "两个竞品";
  return items.map((item) => `竞品 ${item.index + 1}`).join("、");
}

function findings(groups, direction, total) {
  return groups.filter((group) => group.comparisons.some((item) => item.direction === direction))
    .sort((a, b) => b.comparisons.filter((item) => item.direction === direction).length - a.comparisons.filter((item) => item.direction === direction).length)
    .map((group) => {
      const matches = group.comparisons.filter((item) => item.direction === direction);
      return `<span class="overall-point"><strong>${escape(group.labels.join("、"))}${direction > 0 ? "领先" : "落后"}</strong><span class="comparison-scope">${target(matches, total)}</span></span>`;
    }).join("");
}

/**
 * 功能说明：渲染一个可点击的总体优劣势区，使用示例指标演示信息组织方式。
 * 参数：context 包含 self 本品、competitors 竞品及其可用状态、metrics 指标定义。
 * 返回值：无；保存当前比较并更新预览页面。
 */
export function renderOverallSummary(context) {
  comparison = { ...context, ...summarize(context) };
  const { competitors, groups } = comparison;
  const total = competitors.length;
  const missing = competitors.map((item, index) => !item.available ? `竞品 ${index + 1}` : null).filter(Boolean);
  document.querySelector("#summaries").innerHTML = `<button class="summary overall-summary" data-detail="overall" aria-haspopup="dialog" aria-controls="detail" aria-label="查看总体优劣势及各竞品对比依据">
    <span class="overall-heading">总体优劣势</span>
    <span class="overall-columns">
      <span class="overall-side weak"><span class="overall-label">弱势</span><span class="overall-points">${findings(groups, -1, total) || '<span class="overall-empty">暂无明显落后指标</span>'}</span></span>
      <span class="overall-side strong"><span class="overall-label">优势</span><span class="overall-points">${findings(groups, 1, total) || '<span class="overall-empty">暂无明显领先指标</span>'}</span></span>
    </span>
    ${missing.length ? `<span class="overall-unavailable">${missing.join("、")}暂无报告，未参与总结</span>` : ""}
  </button>`;
}

function display(value, metric) {
  if (!Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: metric.decimals }).format(value)}${metric.unit}`;
}

/**
 * 功能说明：展开总体结论的逐条数值依据，以及每个竞品对应的弱势和优势。
 * 参数：无，使用最近一次渲染的 comparison 示例数据。
 * 返回值：无，打开原生对话框，支持 Escape 关闭。
 */
export function showOverallDetail() {
  const { competitors, rows } = comparison;
  document.querySelector("#detail-title").textContent = "总体优劣势";
  document.querySelector("#detail-context").textContent = comparison.self.name;
  document.querySelector("#detail-content").innerHTML = [-1, 1].map((direction) => {
    const selected = rows.filter((row) => row.comparisons.some((item) => item.direction === direction));
    return `<section class="detail-section ${direction < 0 ? "weak" : "strong"}"><h3>${direction < 0 ? "弱势" : "优势"}</h3><ul>${selected.map((row) => {
      const matches = row.comparisons.filter((item) => item.direction === direction);
      return `<li><strong>${escape(row.metric.label)}${direction < 0 ? "落后" : "领先"}${target(matches, competitors.length)}</strong><p>本品 ${display(row.selfValue, row.metric)}；${matches.map((item) => `竞品 ${item.index + 1} ${display(item.value, row.metric)}`).join("；")}。</p></li>`;
    }).join("") || "<li>暂无对应指标。</li>"}</ul></section>`;
  }).join("") + `<section class="detail-section individual-breakdown"><h3>分竞品看</h3>${competitors.map((item, index) => {
    const labels = (direction) => rows.filter((row) => row.comparisons[index].direction === direction).map((row) => row.metric.label).join("、") || "暂无";
    return `<article><h4>竞品 ${index + 1} · ${escape(item.shortName || item.name)}</h4>${item.available ? `<p class="weak">弱势：${escape(labels(-1))}</p><p class="strong">优势：${escape(labels(1))}</p>` : '<p class="subtle">暂无报告</p>'}</article>`;
  }).join("")}</section>`;
  document.querySelector("#detail").showModal();
}
