import demo from "./multi-competitor-data.json";

// 演示数据独立维护，预览页面不请求正式 API，也不保存业务数据。
const state = { product: demo.products[0].id, competitor: demo.products[0].competitors[0].id, date: demo.dates[0], metric: demo.metrics[0].key };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const product = () => demo.products.find((item) => item.id === state.product);
const competitor = () => product().competitors.find((item) => item.id === state.competitor);
const format = (value, metric) => `${value.toLocaleString("zh-CN", { minimumFractionDigits: metric.decimals, maximumFractionDigits: metric.decimals })}${metric.unit === "%" ? "%" : ""}`;

function productContent(item, detail) {
  return `<img class="product-image" src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}主图" referrerpolicy="no-referrer"><span class="product-copy"><strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong><small>${escapeHtml(detail)}</small></span>`;
}

function closeMenu(restoreFocus = false) {
  $("self-menu").hidden = true;
  $("self-trigger").setAttribute("aria-expanded", "false");
  if (restoreFocus) $("self-trigger").focus();
}

/**
 * 功能说明：渲染本品与关联竞品选择区，商品跳转使用独立链接。
 * 参数：无，使用 state 中的当前选择和 demo 中的商品配置。
 * 返回值：无，更新选择区 DOM。
 */
function renderProducts() {
  const current = product();
  $("self-trigger").innerHTML = `${productContent(current, `SPU ${current.id}`)}<span class="chevron" aria-hidden="true">⌄</span>`;
  $("self-link").href = `https://item.jd.com/${current.id}.html`;
  $("self-link").setAttribute("aria-label", `在京东打开${current.name}`);
  $("self-menu").innerHTML = demo.products.map((item) => `<button type="button" role="option" aria-selected="${item.id === current.id}" data-product="${item.id}">${productContent(item, `${item.competitors.length} 个关联竞品`)}<span class="check">${item.id === current.id ? "✓" : ""}</span></button>`).join("");
  $("competitor-count").textContent = current.competitors.length;
  $("competitors").innerHTML = current.competitors.map((item) => `<div class="competitor"><button type="button" data-competitor="${item.id}" aria-label="对比${escapeHtml(item.name)}" aria-pressed="${item.id === state.competitor}">${productContent(item, item.missingDates.includes(state.date) ? "所选日期暂无报告" : `SPU ${item.id}`)}<span class="selection-check" aria-hidden="true">✓</span></button><a class="jd-link" href="https://item.jd.com/${item.id}.html" target="_blank" rel="noopener noreferrer" aria-label="在京东打开${escapeHtml(item.name)}">京东商品 ↗</a></div>`).join("");
  // 图片加载失败时保留尺寸和替代文字，避免商品选择区跳动。
  document.querySelectorAll(".product-image").forEach((image) => image.addEventListener("error", () => { image.alt = "暂无主图"; }, { once: true }));
}

/**
 * 功能说明：根据当前商品对、日期和指标绘制七日示意趋势。
 * 参数：无，使用 state 当前选择及独立示例数据。
 * 返回值：无，更新可访问的 SVG 图表。
 */
function renderChart() {
  const metric = demo.metrics.find((item) => item.key === state.metric);
  const self = product();
  const comp = competitor();
  const lines = [self, comp].map((item) => item.trend.map((factor) => factor * item.metrics[metric.key]));
  const max = Math.max(...lines.flat()) * 1.15;
  const x = (i) => 55 + i * 100;
  const y = (value) => 218 - value / max * 192;
  const ticks = Array.from({ length: 5 }, (_, i) => max * i / 4);
  const dates = Array.from({ length: 7 }, (_, i) => {
    const date = new Date(`${state.date}T00:00:00+08:00`);
    date.setTime(date.getTime() - (6 - i) * 86400000);
    return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit" }).format(date).replace("/", "-");
  });
  $("chart-title").textContent = `${metric.label}趋势`;
  $("chart-competitor").textContent = comp.shortName;
  $("chart").innerHTML = `<svg viewBox="0 0 690 260" role="img" aria-label="${escapeHtml(self.name)}与${escapeHtml(comp.name)}的${metric.label}七日示例趋势"><title>示例趋势，不代表真实业务数据</title>${ticks.map((value) => `<line x1="55" y1="${y(value)}" x2="655" y2="${y(value)}" stroke="#ded6c8" stroke-dasharray="3 4"/><text x="43" y="${y(value) + 4}" text-anchor="end" fill="#667085" font-size="11">${value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(metric.decimals ? 1 : 0)}</text>`).join("")}${lines.map((values, index) => `<polyline points="${values.map((value, i) => `${x(i)},${y(value)}`).join(" ")}" fill="none" stroke="${index ? "#b96905" : "#0f7b73"}" stroke-width="2.5" stroke-linejoin="round"/>${values.map((value, i) => `<circle cx="${x(i)}" cy="${y(value)}" r="${i === 6 ? 5 : 3}" fill="${index ? "#b96905" : "#0f7b73"}" stroke="#fffdf8" stroke-width="1.5"><title>${dates[i]} · ${index ? escapeHtml(comp.name) : "本品"}：${format(value, metric)}</title></circle>`).join("")}`).join("")}${dates.map((date, i) => `<text x="${x(i)}" y="247" text-anchor="middle" fill="#667085" font-size="11">${date}</text>`).join("")}</svg>`;
}

/**
 * 功能说明：按当前选择展示一对一报告；无报告时保留日期并隐藏全部旧报告内容。
 * 参数：无，使用 state 当前选择。
 * 返回值：无，更新报告区域和读屏提示。
 */
function renderReport() {
  const self = product();
  const comp = competitor();
  const missing = comp.missingDates.includes(state.date);
  $("current-pair").textContent = `正在对比：${self.name} × ${comp.shortName}`;
  $("empty").hidden = !missing;
  $("report-content").hidden = missing;
  $("empty-context").textContent = `${state.date} · ${self.name} × ${comp.name}`;
  $("announcement").textContent = `${state.date}，已切换至${comp.name}${missing ? "，暂无报告" : "，示例报告已展示"}`;
  if (missing) return;
  $("strength").textContent = comp.strength;
  $("weakness").textContent = comp.weakness;
  $("insight-scope").textContent = `针对「${comp.shortName}」的建议`;
  $("advice").innerHTML = comp.advice.map((item) => `<li><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)}</p></li>`).join("");
  $("metrics").innerHTML = demo.metrics.map((metric) => {
    const gap = self.metrics[metric.key] - comp.metrics[metric.key];
    return `<button class="metric" type="button" data-metric="${metric.key}" aria-pressed="${metric.key === state.metric}"><span class="metric-label">${metric.label}<span class="gap ${gap >= 0 ? "positive" : ""}">${gap >= 0 ? "+" : ""}${gap.toFixed(metric.decimals)}${metric.unit === "%" ? "pct" : metric.unit}</span></span><span class="numbers"><span><strong>${format(self.metrics[metric.key], metric)}</strong><small>本品真实值</small></span><span><strong>${format(comp.metrics[metric.key], metric)}</strong><small>竞品估算值</small></span></span></button>`;
  }).join("");
  renderChart();
}

$("report-date").innerHTML = demo.dates.map((date) => `<option value="${date}">${date.replace(/-/g, "/")}</option>`).join("");
$("report-date").addEventListener("change", (event) => { state.date = event.target.value; renderProducts(); renderReport(); });
$("self-trigger").addEventListener("click", () => {
  const open = $("self-menu").hidden;
  $("self-menu").hidden = !open;
  $("self-trigger").setAttribute("aria-expanded", String(open));
  if (open) $("self-menu").querySelector('[aria-selected="true"]').focus();
});
$("self-menu").addEventListener("click", (event) => {
  const button = event.target.closest("[data-product]");
  if (!button) return;
  state.product = button.dataset.product;
  state.competitor = product().competitors[0].id;
  closeMenu(true);
  renderProducts(); renderReport();
});
$("self-menu").addEventListener("keydown", (event) => {
  const buttons = [...$("self-menu").querySelectorAll("button")];
  const index = buttons.indexOf(document.activeElement);
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
  buttons[next].focus();
});
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("self-menu").hidden) closeMenu(true); });
document.addEventListener("click", (event) => { if (!event.target.closest(".self-picker")) closeMenu(); });
$("competitors").addEventListener("click", (event) => {
  const button = event.target.closest("[data-competitor]");
  if (!button) return;
  state.competitor = button.dataset.competitor;
  renderProducts(); renderReport();
  $("competitors").querySelector('[aria-pressed="true"]').focus({ preventScroll: true });
});
$("metrics").addEventListener("click", (event) => {
  const button = event.target.closest("[data-metric]");
  if (!button) return;
  state.metric = button.dataset.metric;
  renderReport();
  $("metrics").querySelector('[aria-pressed="true"]').focus({ preventScroll: true });
});
renderProducts(); renderReport();
