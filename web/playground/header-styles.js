const examples = document.querySelector('#examples');
const menu = document.querySelector('#menu');
const variants = [
  ['a', '紧凑横栏', '选品、对比、日期集中在一行，优先给报告内容留空间。'],
  ['b', '标签导航', '本品是上下文，竞品是标签；日期与 SKU 放在标题右侧。'],
  ['c', '左右对比', '主图与名称左右展开，选择状态使用轻底色，操作放在底部。'],
  ['d', '轻量排版', '弱化卡片，用留白与细分隔组织本品、竞品和操作。'],
  ['e', '操作分层', '上面只负责选品，下面集中日期、粒度和 SKU，保持清晰层次。'],
];
let data;
let count = 2;
let activeTrigger;
const states = new Map();
const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char]));

function image(product) {
  return `<img class="photo" src="${escape(product.image)}" alt="${escape(product.name)}主图" referrerpolicy="no-referrer">`;
}
function content(product) {
  return `${image(product)}<span class="copy"><span class="name">${escape(product.name)}</span><span class="id">商品 ID ${escape(product.id)}</span></span>`;
}
function competitors(product) {
  // 多竞品压力预览复用素材配置，不更改真实商品关系。
  const pool = [...product.competitors, ...data.products.flatMap((item) => item.competitors)];
  return [...new Map(pool.map((item) => [item.id, item])).values()].slice(0, count);
}
function productMarkup(product, action, active = false, dropdown = false) {
  return `<div class="product${active ? ' active' : ''}"><button class="choose" data-action="${action}" data-id="${escape(product.id)}" ${dropdown ? 'aria-haspopup="listbox" aria-expanded="false"' : `aria-pressed="${active}"`} aria-label="${action === 'self' ? '切换本品' : '选择竞品'}：${escape(product.name)}">${content(product)}<span class="arrow" aria-hidden="true">${dropdown ? '⌄' : active ? '✓' : ''}</span></button><a class="external" href="https://item.jd.com/${encodeURIComponent(product.id)}.html" target="_blank" rel="noopener noreferrer" aria-label="在京东打开${escape(product.name)}">↗</a></div>`;
}
function controls(state) {
  return `<div class="tools"><select aria-label="分析粒度" data-control="granularity"><option value="day" ${state.granularity === 'day' ? 'selected' : ''}>日</option><option value="week" ${state.granularity === 'week' ? 'selected' : ''}>周</option><option value="month" ${state.granularity === 'month' ? 'selected' : ''}>月</option></select><input class="date" aria-label="分析日期" type="date" value="${state.date}" data-control="date"><button class="sku" data-action="sku">查看 SKU</button></div>`;
}

/**
 * 功能说明：生成五种独立可交互页头，业务素材读取本地预览配置。
 * 参数：无，使用 states 保存每个方案的商品、竞品和周期选择。
 * 返回值：无，更新预览 DOM。
 */
function render() {
  closeMenu();
  examples.innerHTML = variants.map(([key, title, note]) => {
    const state = states.get(key);
    const self = data.products.find((item) => item.id === state.self);
    const rivals = competitors(self);
    const current = rivals.find((item) => item.id === state.competitor) || rivals[0];
    state.competitor = current.id;
    const compactRival = key === 'a' || rivals.length > 2;
    const rivalMarkup = compactRival ? productMarkup(current, 'menu', true, true) : `<div class="rival-list">${rivals.map((item) => productMarkup(item, 'competitor', item.id === current.id)).join('')}</div>`;
    const tools = controls(state);
    return `<section class="example" id="${key}" data-variant="${key}"><header class="caption"><span class="letter">${key.toUpperCase()}</span><div><h2>${title}</h2><p>${note}</p></div></header><div class="stage layout-${key}"><div class="topline"><h3>竞品准真实值看板</h3>${key === 'b' ? tools : '<span class="fresh"><i></i>数据更新于 12:05 · 示例</span>'}</div><div class="workbench"><div class="self"><div class="label">本品</div>${productMarkup(self, 'self', false, true)}</div>${key === 'c' ? '<div class="versus">VS</div>' : ''}<div class="rivals"><div class="label">对比竞品 <b>${rivals.length} 个</b></div>${rivalMarkup}</div>${['a','d'].includes(key) ? tools : ''}</div><div class="scope">${['c','e'].includes(key) ? tools : `<span class="current">当前对比：<strong>${escape(current.name)}</strong></span>`}<span>${key === 'b' ? '数据更新于 12:05 · 示例' : `${escape(state.date)} · ${{ day:'日报', week:'自然周报', month:'月报' }[state.granularity]}`}</span></div></div></section>`;
  }).join('');
  examples.querySelectorAll('img').forEach((img) => img.addEventListener('error', () => { img.alt = '暂无主图'; }, { once:true }));
}
function closeMenu(restore = false) {
  menu.hidden = true;
  activeTrigger?.setAttribute('aria-expanded', 'false');
  if (restore) activeTrigger?.focus();
}

/**
 * 功能说明：展示有主图的本品或竞品列表，支持搜索、键盘与关闭操作。
 * 参数 trigger：触发菜单的按钮，作为定位和焦点还原目标。
 * 参数 key：方案标识，用于更新对应方案状态。
 * 参数 isSelf：是否选择本品；false 时选择当前本品的竞品。
 * 返回值：无，打开菜单并定位到可操作元素。
 */
function openMenu(trigger, key, isSelf) {
  if (!menu.hidden && activeTrigger === trigger) { closeMenu(true); return; }
  closeMenu();
  activeTrigger = trigger;
  trigger.setAttribute('aria-expanded', 'true');
  const state = states.get(key);
  const self = data.products.find((item) => item.id === state.self);
  const items = isSelf ? data.products : competitors(self);
  menu.innerHTML = `${items.length > 2 ? '<input type="search" aria-label="搜索商品" placeholder="搜索名称或 ID">' : ''}<div role="listbox" aria-label="${isSelf ? '本品' : '竞品'}"></div>`;
  const list = menu.querySelector('[role="listbox"]');
  const draw = (query = '') => {
    const matches = items.filter((item) => `${item.name} ${item.id}`.toLowerCase().includes(query.toLowerCase()));
    list.innerHTML = matches.length ? matches.map((item) => `<button class="choose" role="option" aria-selected="${item.id === (isSelf ? state.self : state.competitor)}" data-id="${item.id}">${content(item)}<span class="arrow">${item.id === (isSelf ? state.self : state.competitor) ? '✓' : ''}</span></button>`).join('') : '<p class="empty" role="status">没有匹配的商品</p>';
  };
  draw();
  menu.hidden = false;
  const rect = trigger.getBoundingClientRect();
  const width = Math.min(360, innerWidth - 24);
  menu.style.width = `${width}px`;
  menu.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`;
  menu.style.top = `${rect.bottom + 6}px`;
  if (rect.bottom + 6 + menu.offsetHeight > innerHeight - 12) menu.style.top = `${Math.max(12, rect.top - menu.offsetHeight - 6)}px`;
  menu.querySelector('input')?.addEventListener('input', (event) => draw(event.target.value));
  list.onclick = (event) => {
    const option = event.target.closest('[role="option"]');
    if (!option) return;
    state[isSelf ? 'self' : 'competitor'] = option.dataset.id;
    render();
    document.querySelector(`#${key} [data-action="${isSelf ? 'self' : 'menu'}"]`)?.focus();
  };
  (menu.querySelector('input') || list.querySelector('[aria-selected="true"]') || list.querySelector('button'))?.focus();
}
examples.addEventListener('click', (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const key = button.closest('[data-variant]').dataset.variant;
  const action = button.dataset.action;
  if (action === 'self' || action === 'menu') openMenu(button, key, action === 'self');
  if (action === 'competitor') { states.get(key).competitor = button.dataset.id; render(); document.querySelector(`#${key} [data-id="${button.dataset.id}"]`)?.focus(); }
  if (action === 'sku') document.querySelector('dialog').showModal();
});
examples.addEventListener('change', (event) => {
  const control = event.target.dataset.control;
  if (!control) return;
  const key = event.target.closest('[data-variant]').dataset.variant;
  states.get(key)[control] = event.target.value;
  render();
  document.querySelector(`#${key} [data-control="${control}"]`)?.focus();
});
document.addEventListener('click', (event) => { if (!menu.contains(event.target) && !event.target.closest('[aria-haspopup]')) closeMenu(); });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeMenu(true);
  if (!menu.hidden && ['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
    if (event.target.matches('input') && ['Home','End'].includes(event.key)) return;
    event.preventDefault();
    const options = [...menu.querySelectorAll('[role="option"]')];
    const current = options.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : Math.max(0, Math.min(options.length - 1, current + (event.key === 'ArrowDown' ? 1 : -1)));
    options[next]?.focus();
  }
});
window.addEventListener('scroll', () => closeMenu(), { passive:true });
window.addEventListener('resize', () => closeMenu());
document.querySelector('#close-dialog').onclick = () => document.querySelector('dialog').close();
document.querySelector('#count').onchange = (event) => { count = Number(event.target.value); render(); };
document.querySelector('#palette').onchange = (event) => { document.body.dataset.palette = event.target.value; };
document.querySelector('#density').onchange = (event) => { document.body.dataset.density = event.target.value; };
try {
  const response = await fetch('./multi-competitor-data.json');
  if (!response.ok) throw new Error(`素材读取失败：${response.status}`);
  data = await response.json();
  variants.forEach(([key]) => states.set(key, { self:data.products[0].id, competitor:data.products[0].competitors[0].id, date:data.dates[0], granularity:'day' }));
  render();
} catch (error) {
  console.error('页头预览加载失败', error);
  examples.textContent = '预览素材加载失败，请刷新重试。';
}
