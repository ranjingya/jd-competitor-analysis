// 使用隔离的测试商品标识和模拟 API，不向正式 API 发请求。
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const log = [];
function check(condition, message) {
  if (!condition) throw new Error(message);
  log.push(`通过：${message}`);
}
async function until(predicate) {
  for (let i = 0; i < 300; i++) { if (predicate()) return; await sleep(10); }
  throw new Error('等待页面状态超时');
}
const today = '2026-09-03';
const yesterday = '2026-09-02';
const configs = [
  { self: '101', comp: '201', date: today },
  { self: '101', comp: '202', date: yesterday },
  { self: '102', comp: '203', date: today },
  { self: '102', comp: '204', date: today },
  { self: '102', comp: '205', date: today },
];
const entries = configs.map((item) => ({
  self_spu: item.self, competitor_spu: item.comp, self_name: `测试本品${item.self}`,
  competitor_name: `测试竞品${item.comp}`, report_id: `${item.self}-${item.comp}`,
  granularity: 'day', start_date: item.date, end_date: item.date, period: item.date,
  updated_at: `${today}T12:00:00+08:00`, path: `/api/reports/${item.self}-${item.comp}`,
}));
const reportFor = (entry) => ({
  meta: { period: entry.period, granularity: 'day', summary: `优点${entry.competitor_spu}`, weakness_summary: `弱点${entry.competitor_spu}` },
  core_metrics: [{ id: 'gmv', label: '成交金额', self_value: 100, competitor_value: Number(entry.competitor_spu), gap_value: 100 - Number(entry.competitor_spu), status: 'warning', unit: '' }],
  tabs: [], ai_recommendations: [], risks: [],
});
const nativeFetch = window.fetch.bind(window);
const source = await (await nativeFetch('/index.html')).text();
const parsed = new DOMParser().parseFromString(source, 'text/html');
parsed.querySelectorAll('script').forEach((script) => script.remove());
document.body.innerHTML = parsed.body.innerHTML;
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.href);
  if (!url.pathname.startsWith('/api/')) return nativeFetch(input, init);
  let data;
  if (url.pathname === '/api/product-pairs') {
    data = { items: entries.map((entry) => ({ ...entry, latest_reports: { day: entry }, report_counts: { day: 1, week: 0, month: 0 } })) };
  } else if (url.pathname === '/api/reports/periods') {
    const found = entries.filter((entry) => entry.self_spu === url.searchParams.get('self_spu') && entry.competitor_spu === url.searchParams.get('competitor_spu'));
    await sleep(url.searchParams.get('competitor_spu') === '202' ? 150 : 5);
    data = { items: found, contexts: ['2026-09'] };
  } else if (url.pathname === '/api/reports/trends') {
    data = { items: [] };
  } else {
    const entry = entries.find((item) => item.path === url.pathname);
    if (!entry) return new Response('{}', { status: 404 });
    await sleep(entry.competitor_spu === '204' ? 150 : 5);
    data = reportFor(entry);
  }
  return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
const $ = (selector) => document.querySelector(selector);
const option = (text) => [...document.querySelectorAll('.product-select-option')].find((node) => node.textContent.includes(text));
const chooseSelf = (id) => { $('#pair-trigger').click(); option(`测试本品${id}`).click(); };
const card = (id) => $(`.product-select-card[data-pair-key="101::${id}"]`);
const settled = () => !$('#dashboard').hidden && !$('#updated-at').textContent.includes('正在');
const chooseComp = (id) => { $('#competitor-trigger').click(); option(`测试竞品${id}`).click(); };

/**
 * 功能说明：在真实页面 DOM 上验证分组、搜索、空报告和异步切换。
 * 参数：无，使用本模块隔离的测试响应。
 * 返回值：Promise，结束时向父页面发送测试结果。
 */
async function run() {
  await import('/src/main.js');
  await until(settled);
  $('#pair-trigger').click();
  check(document.querySelectorAll('#pair-trigger-list button').length === 2, '本品去重为两项');
  option('测试本品101').click();
  await until(settled);
  check(document.querySelectorAll('[data-pair-key]').length === 2, '两个竞品展示卡片');
  const selectedDate = $('#period-trigger').textContent;
  card('202').click();
  await until(() => !$('#page-state').hidden && $('#page-state').textContent.includes('暂无报告'));
  check($('#period-trigger').textContent === selectedDate, '缺失报告保留所选日期');
  check($('#dashboard').hidden && $('#sku-trigger').disabled, '缺失报告隐藏旧内容并禁用 SKU');
  $('#period-trigger').click();
  check(!document.querySelector('[data-report-id].is-selected'), '无报告的日历不误选其他日期');
  const bounds = $('#period-popover').getBoundingClientRect();
  check(bounds.left >= 0 && bounds.right <= innerWidth + 1, '日历不超出视口');
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  card('201').click();
  await until(settled);
  card('202').click();
  card('201').click();
  await sleep(220);
  check(settled() && $('#metrics').textContent.includes('201.00'), '快速切换不被旧空报告请求覆盖');
  chooseSelf('102');
  await until(settled);
  check(!!$('#competitor-trigger') && !document.querySelector('[data-pair-key]'), '三个竞品使用下拉框');
  $('#competitor-trigger').click();
  const search = $('.product-select-search');
  search.value = '204';
  search.dispatchEvent(new Event('input', { bubbles: true }));
  check(document.querySelectorAll('#competitor-trigger-list button').length === 1, '支持按竞品 ID 搜索');
  search.value = '无匹配';
  search.dispatchEvent(new Event('input', { bubbles: true }));
  check(!!$('.product-select-empty'), '搜索无结果状态');
  search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  check($('#competitor-trigger').getAttribute('aria-expanded') === 'false' && document.activeElement === $('#competitor-trigger'), 'Esc 收起并恢复焦点');
  chooseComp('204');
  chooseComp('205');
  await sleep(230);
  check(settled() && $('#metrics').textContent.includes('205.00'), '慢报告响应不覆盖最新竞品');
  $('#pair-trigger').click();
  document.body.click();
  check($('#pair-trigger').getAttribute('aria-expanded') === 'false', '点击外部关闭菜单');
  check(document.documentElement.scrollWidth <= innerWidth, '页面没有横向溢出');
}
run().then(() => parent.postMessage({ type: 'navigation-test', result: log.join('\n') }, location.origin))
  .catch((error) => parent.postMessage({ type: 'navigation-test', result: `${log.join('\n')}\n失败：${error.message}` }, location.origin));
