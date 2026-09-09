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
  { self: '103', comp: '205', date: today },
  { self: '104', comp: '206', date: today },
  { self: '104', comp: '207', date: today },
  { self: '105', comp: '208', date: yesterday },
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
  tabs: [{ id: 'traffic', label: '流量来源', columns: [
    { key: 'path', label: '渠道路径' },
    { key: 'self_visitors', label: '本品访客' },
    { key: 'competitor_visitors', label: '竞品访客' },
    { key: 'visitor_gap', label: '访客差距' },
    { key: 'self_gmv', label: '本品成交金额' },
    { key: 'competitor_gmv', label: '竞品成交金额' },
    { key: 'gmv_gap', label: '成交金额差距' }
  ], rows: [{ path: '测试渠道', level_1: '测试渠道', self_visitors: 100, competitor_visitors: 90, visitor_gap: 10, self_gmv: 200, competitor_gmv: 300, gmv_gap: -100 }] }], ai_recommendations: [], risks: [],
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
    data = { items: [yesterday, today].map((date) => ({
      meta: { period_start: date, period_end: date, period: date },
      core_metrics: [{ id: 'gmv', label: '成交金额', unit: '', self_value: 100, competitor_value: Number(url.searchParams.get('competitor_spu')) }]
    })) };
  } else {
    const entry = entries.find((item) => item.path === url.pathname);
    if (!entry) return new Response('{}', { status: 404 });
    if (entry.competitor_spu === '206') return new Response('{}', { status: 500 });
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

/**
 * 功能说明：在真实页面 DOM 上验证单／双竞品、商品链接、空报告和异步切换。
 * 参数：无，使用本模块隔离的测试响应。
 * 返回值：Promise，结束时向父页面发送测试结果。
 */
async function run() {
  await import('/src/main.js');
  await until(settled);
  chooseSelf('101');
  await until(settled);
  check(document.querySelectorAll('.product-select-item').length === 3, '本品与双竞品同屏');
  check($('#hero-summaries').textContent.includes('对比竞品 1') && $('#hero-summaries').textContent.includes('所选周期暂无报告'), '一侧缺失只显示该侧空状态');
  check($('#metrics').textContent.includes('201.00') && !$('#metrics').textContent.includes('202.00'), '缺失侧不拿其他日期报告填充');
  check(!$('#sku-trigger').disabled, '另一侧有报告仍可查看本品 SKU');
  check($('[data-measure="all"]').getAttribute('aria-pressed') === 'true' && !$('#comparison-measure'), '指标默认全部且使用按钮而非下拉框');
  $('[data-measure="self_visitors"]').click();
  check($('[data-measure="self_visitors"]').getAttribute('aria-pressed') === 'true' && document.activeElement === $('[data-measure="self_visitors"]'), '切换指标保留键盘焦点与选中状态');
  await until(() => document.querySelectorAll('.vxe-table--main-wrapper .vxe-header--column').length === 6);
  const headers = [...document.querySelectorAll('.vxe-table--main-wrapper .vxe-header--column')];
  check(headers.length === 6 && headers[1].classList.contains('analysis-derived-header') && headers[2].classList.contains('analysis-derived-header') && !headers[3].classList.contains('analysis-derived-header'), '访客指标蓝色计算列位于名称列后和原始列前');
  $('[data-measure="all"]').click();
  check(document.querySelectorAll('.product-select-link').length === 3 && !document.querySelector('.product-select-card a'), '商品主图链接独立');
  check([...document.querySelectorAll('.product-select-link')].every((link) => {
    const a = link.getBoundingClientRect(), b = link.firstElementChild.getBoundingClientRect();
    return a.width === b.width && a.height === b.height && a.left === b.left && a.top === b.top;
  }), '主图 hover 边框紧贴图片');
  const selectedDate = $('#period-trigger').textContent;
  card('202').querySelector('strong').click();
  check($('#period-trigger').textContent === selectedDate && !$('#dashboard').hidden, '点击竞品文字不跳转、不切换日期');
  let photoClicked = false;
  const photoLink = card('202').parentElement.querySelector('.product-select-link');
  photoLink.addEventListener('click', (event) => { event.preventDefault(); photoClicked = true; }, { once:true });
  photoLink.click();
  check(photoClicked && $('#metrics').textContent.includes('201.00'), '点击主图只打开商品链接');
  if (innerWidth > 1050) {
    const positions = [...document.querySelectorAll('.product-select-item')].map((node) => node.getBoundingClientRect().top);
    check(positions.every((top) => top === positions[0]), '宽屏三个商品同一行');
  }
  $('#period-trigger').click();
  const bounds = $('#period-popover').getBoundingClientRect();
  check(bounds.left >= 0 && bounds.right <= innerWidth + 1, '日历不超出视口');
  check([...document.querySelectorAll('[data-report-id]')].some((node) => node.dataset.reportId === '101-202'), '日历包含另一竞品独有的日期');
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  chooseSelf('102');
  await until(settled);
  check($('#metrics').textContent.includes('203.00') && $('#metrics').textContent.includes('204.00'), '双竞品指标同时加载');
  await until(() => $('#trend-chart svg'));
  check($('#trend-chart').textContent.includes('竞品 1') && $('#trend-chart').textContent.includes('竞品 2'), '三条趋势线共享图例');
  const summaries = [...document.querySelectorAll('[data-summary-index]')];
  summaries[1].click();
  check($('#summary-dialog-title').textContent.includes('竞品 2'), '详情明确竞品编号');
  check($('#summary-dialog-weakness').textContent.includes('204'), '详情来自所点击竞品');
  check($('#summary-dialog-weakness').children.length > 0, '详情分点展示');
  $('#summary-dialog').close();
  await sleep(20);
  summaries[0].click();
  check($('#summary-dialog-advantage').textContent.includes('203'), '反复打开详情不会串竞品');
  $('#summary-dialog').close();
  chooseSelf('103');
  await until(settled);
  check(document.querySelectorAll('.product-select-item').length === 2 && document.querySelectorAll('[data-summary-index]').length === 1, '单竞品布局自动收拢');
  chooseSelf('102');
  chooseSelf('103');
  await sleep(250);
  check(settled() && $('#metrics').textContent.includes('205.00') && !$('#metrics').textContent.includes('204.00'), '旧请求不覆盖最新本品');
  chooseSelf('104');
  await until(settled);
  check($('#hero-summaries').textContent.includes('报告读取失败') && $('#metrics').textContent.includes('207.00'), '首个竞品读取失败不影响第二个竞品');
  check($('#hero-summaries [data-summary-index="0"]').disabled && !$('#hero-summaries [data-summary-index="1"]').disabled, '失败侧空槽不改变竞品编号');
  chooseSelf('105');
  await until(() => !$('#page-state').hidden && $('#page-state').textContent.includes('暂无报告'));
  check($('#dashboard').hidden && $('#sku-trigger').disabled, '所选日双方无报告时清空旧看板');
  chooseSelf('103');
  await until(settled);
  $('#pair-trigger').click();
  document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
  check(document.activeElement === $('#pair-trigger-list').lastElementChild, '本品菜单键盘导航');
  document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  check($('#pair-trigger').getAttribute('aria-expanded') === 'false' && document.activeElement === $('#pair-trigger'), 'Esc 收起并恢复焦点');
  $('#pair-trigger').click();
  document.body.click();
  check($('#pair-trigger').getAttribute('aria-expanded') === 'false', '点击外部关闭菜单');
  check(document.documentElement.scrollWidth <= innerWidth, '页面没有横向溢出');
}
run().then(() => parent.postMessage({ type: 'navigation-test', result: log.join('\n') }, location.origin))
  .catch((error) => parent.postMessage({ type: 'navigation-test', result: `${log.join('\n')}\n失败：${error.message}` }, location.origin));
