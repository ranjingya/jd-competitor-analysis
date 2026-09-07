const root = document.querySelector('#products');
const menu = document.querySelector('#self-menu');
const state = { count:2, self:null, competitor:null };
let data;
const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char]));

function details(product, self) {
  return `<img class="photo" src="${escape(product.image)}" alt="${escape(product.name)}主图" referrerpolicy="no-referrer"><span class="copy"><span class="topline"><span class="role ${self ? '' : 'competitor'}">${self ? '本品' : '竞品'}</span><span class="name">${escape(product.name)}</span></span><span class="id">商品 ID ${escape(product.id)}</span></span>`;
}
function card(product, self) {
  const selected = !self && product.id === state.competitor;
  return `<div class="product${selected ? ' is-active' : ''}"><button class="switch" data-id="${product.id}" ${self ? 'id="self-trigger" aria-haspopup="listbox" aria-expanded="false" aria-controls="self-menu"' : `aria-pressed="${selected}"`} aria-label="${self ? '切换本品' : `对比${escape(product.name)}`}"><span class="marker" aria-hidden="true">${self ? '⌄' : selected ? '✓' : '○'}</span></button><a class="product-link" href="https://item.jd.com/${encodeURIComponent(product.id)}.html" target="_blank" rel="noopener noreferrer" aria-label="在京东打开${escape(product.name)}">${details(product, self)}</a></div>`;
}
function fallbackImages(container) {
  container.querySelectorAll('img').forEach((img) => img.addEventListener('error', () => {
    const placeholder = document.createElement('span');
    placeholder.className = 'photo photo-fallback';
    placeholder.textContent = '暂无主图';
    img.replaceWith(placeholder);
  }, { once:true }));
}
function closeMenu(focus = false) {
  menu.hidden = true;
  const trigger = document.querySelector('#self-trigger');
  trigger?.setAttribute('aria-expanded','false');
  if (focus) trigger?.focus();
}

/**
 * 功能说明：展示当前本品及一至两个竞品，保留商品京东链接和独立选择操作。
 * 参数：无，从预览配置和 state 读取商品关系与竞品数量。
 * 返回值：无，更新商品选择区，不请求业务 API。
 */
function render() {
  closeMenu();
  const self = data.products.find((item) => item.id === state.self);
  const competitors = self.competitors.slice(0, state.count);
  if (!competitors.some((item) => item.id === state.competitor)) state.competitor = competitors[0]?.id;
  root.dataset.count = competitors.length;
  root.innerHTML = card(self, true) + competitors.map((item) => card(item, false)).join('');
  fallbackImages(root);
  const current = competitors.find((item) => item.id === state.competitor);
  document.querySelector('#selection-status').textContent = `预览当前对比：${self.name} × ${current?.name || '暂无竞品'}。点箭头切换本品，点竞品右侧圆点切换分析；点主图或名称打开京东。`;
}

/**
 * 功能说明：打开含主图的本品下拉菜单，并使弹层保持在视口范围内。
 * 参数：无，使用当前本品按钮定位和 data.products 生成选项。
 * 返回值：无，显示菜单并聚焦选中选项。
 */
function openMenu() {
  if (!menu.hidden) { closeMenu(true); return; }
  const trigger = document.querySelector('#self-trigger');
  menu.innerHTML = data.products.map((product) => `<button class="option" role="option" data-id="${product.id}" aria-selected="${product.id === state.self}">${details(product, true)}<span class="check">${product.id === state.self ? '✓' : ''}</span></button>`).join('');
  fallbackImages(menu);
  menu.hidden = false;
  trigger.setAttribute('aria-expanded','true');
  const bounds = trigger.getBoundingClientRect();
  const width = Math.min(360, innerWidth - 24);
  menu.style.width = `${width}px`;
  menu.style.left = `${Math.max(12,Math.min(bounds.left,innerWidth - width - 12))}px`;
  menu.style.top = `${Math.max(12,Math.min(bounds.bottom + 6,innerHeight - menu.offsetHeight - 12))}px`;
  menu.querySelector('[aria-selected="true"]')?.focus();
}
root.onclick = (event) => {
  const button = event.target.closest('.switch');
  if (!button) return;
  if (button.id === 'self-trigger') { openMenu(); return; }
  state.competitor = button.dataset.id;
  render();
  root.querySelector(`[data-id="${state.competitor}"]`)?.focus();
};
menu.onclick = (event) => {
  const option = event.target.closest('[role="option"]');
  if (!option) return;
  state.self = option.dataset.id;
  render();
  document.querySelector('#self-trigger').focus();
};
document.addEventListener('click', (event) => { if (!menu.contains(event.target) && !event.target.closest('#self-trigger')) closeMenu(); });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeMenu(true);
  if (event.target.id === 'self-trigger' && ['ArrowUp','ArrowDown'].includes(event.key) && menu.hidden) { event.preventDefault(); openMenu(); return; }
  if (menu.hidden || !['ArrowUp','ArrowDown','Home','End'].includes(event.key)) return;
  event.preventDefault();
  const options = [...menu.querySelectorAll('[role="option"]')];
  const index = options.indexOf(document.activeElement);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : Math.max(0,Math.min(options.length - 1,index + (event.key === 'ArrowDown' ? 1 : -1)));
  options[next]?.focus();
});
document.querySelectorAll('button[data-count]').forEach((button) => button.onclick = () => {
  state.count = Number(button.dataset.count);
  document.querySelectorAll('button[data-count]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
  render();
});
window.addEventListener('resize', () => closeMenu());
window.addEventListener('scroll', () => closeMenu(), { passive:true });
document.querySelector('#sku').onclick = () => document.querySelector('dialog').showModal();
document.querySelector('#close-sku').onclick = () => document.querySelector('dialog').close();
try {
  const response = await fetch('./multi-competitor-data.json');
  if (!response.ok) throw new Error(`素材读取失败：${response.status}`);
  data = await response.json();
  state.self = data.products[0].id;
  document.querySelector('#date').value = data.dates[0];
  render();
} catch (error) {
  console.error('商品选择预览加载失败', error);
  root.textContent = '预览素材加载失败，请刷新重试。';
}
