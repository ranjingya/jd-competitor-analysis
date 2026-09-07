import { groupProductPairs } from "./report-selection.js";
import "./product-picker.css";

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function productContent(product, detail) {
  const wrapper = element("span", "product-select-content");
  const frame = element("span", "product-select-image");
  if (product.imageUrl) {
    const image = document.createElement("img");
    image.src = product.imageUrl;
    image.alt = `${product.name || product.id}主图`;
    image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => { image.remove(); frame.textContent = "暂无主图"; }, { once: true });
    frame.append(image);
  } else frame.textContent = "暂无主图";
  const copy = element("span", "product-select-copy");
  const name = element("strong", "", product.name || product.id);
  name.title = name.textContent;
  copy.append(name, element("small", "", detail || `商品 ID ${product.id}`));
  wrapper.append(frame, copy);
  return wrapper;
}

function jdLink(product) {
  const link = element("a", "product-select-link", "京东商品 ↗");
  link.href = `https://item.jd.com/${encodeURIComponent(product.id)}.html`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `在京东打开${product.name || product.id}`);
  return link;
}

function competitorProduct(pair) {
  return { id: pair.competitorSpu, name: pair.competitorName, imageUrl: pair.competitorImageUrl };
}

/**
 * 功能说明：关闭本品或竞品菜单，并按需还原触发器焦点。
 * 参数 container：商品选择器根节点。
 * 参数 pickerState：菜单开合和触发器标识。
 * 参数 restoreFocus：是否恢复触发器焦点。
 * 返回值：原本打开时返回 true，否则返回 false。
 */
export function closePairPicker(container, pickerState, restoreFocus = false) {
  if (!container || !pickerState.open) return false;
  pickerState.open = false;
  pickerState.closing = false;
  container.querySelectorAll(".product-select-menu").forEach((menu) => { menu.hidden = true; });
  container.querySelectorAll('[aria-expanded="true"]').forEach((button) => button.setAttribute("aria-expanded", "false"));
  if (restoreFocus) container.querySelector(`#${pickerState.triggerId}`)?.focus();
  return true;
}

/**
 * 功能说明：构造含图片、键盘导航和可选搜索的单选下拉框。
 * 参数 config：包含 container、pickerState、id、label、items、selected、onSelect、onBeforeOpen、searchable。
 * 返回值：包含触发器、弹层和京东链接的选择区 DOM。
 */
function dropdown(config) {
  const { container, pickerState, id, label, items, selected, onSelect, onBeforeOpen, searchable } = config;
  const root = element("div", "product-select-dropdown");
  const trigger = element("button", "product-select-card");
  trigger.type = "button";
  trigger.id = id;
  trigger.setAttribute("aria-label", label);
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  trigger.setAttribute("aria-controls", `${id}-list`);
  trigger.append(productContent(selected), element("span", "product-select-chevron", "⌄"));
  const menu = element("div", "product-select-menu");
  menu.hidden = true;
  const list = element("div", "product-select-list");
  list.id = `${id}-list`;
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", label);
  let search;
  const drawOptions = (query = "") => {
    const matches = items.filter((item) => `${item.name} ${item.id}`.toLowerCase().includes(query.trim().toLowerCase()));
    list.replaceChildren(...matches.map((item) => {
      const option = element("button", "product-select-option");
      option.type = "button";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(item.id === selected.id));
      option.append(productContent(item, item.detail), element("span", "product-select-check", item.id === selected.id ? "✓" : ""));
      option.onclick = (event) => {
        event.stopPropagation();
        closePairPicker(container, pickerState, true);
        onSelect(item);
        container.querySelector(`#${id}`)?.focus();
      };
      return option;
    }));
    if (!matches.length) {
      const empty = element("p", "product-select-empty", "没有匹配的竞品");
      empty.setAttribute("role", "status");
      list.append(empty);
    }
  };
  if (searchable) {
    search = element("input", "product-select-search");
    search.type = "search";
    search.placeholder = "搜索竞品名称或商品 ID";
    search.setAttribute("aria-label", "搜索竞品");
    search.oninput = () => drawOptions(search.value);
    menu.append(search);
  }
  drawOptions();
  menu.append(list);
  const open = () => {
    closePairPicker(container, pickerState);
    onBeforeOpen?.();
    pickerState.open = true;
    pickerState.triggerId = id;
    if (search) search.value = "";
    drawOptions();
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    (search || list.querySelector('[aria-selected="true"]') || list.querySelector("button"))?.focus();
  };
  trigger.onclick = () => menu.hidden ? open() : closePairPicker(container, pickerState);
  trigger.onkeydown = (event) => {
    if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); open(); }
  };
  menu.onkeydown = (event) => {
    if (event.key === "Escape") { event.preventDefault(); closePairPicker(container, pickerState, true); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    if (event.target === search && ["Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const options = [...list.querySelectorAll("button")];
    const index = options.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
      : Math.max(0, Math.min(options.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
    options[next]?.focus();
  };
  root.append(trigger, menu, jdLink(selected));
  return root;
}

/**
 * 功能说明：按本品组织已有报告的商品对；一至两个竞品使用卡片，更多使用搜索下拉框。
 * 参数 options：根节点、商品对数组、当前商品对、弹层状态和切换回调。
 * 返回值：无，更新商品选择区，不读取飞书或报告正文。
 */
export function renderPairPicker(options) {
  const { container, pairs, activePairKey, pickerState, onBeforeOpen, onPairChange } = options;
  // 周期元数据返回时不重建相同选择器，保留搜索输入和键盘焦点。
  const renderKey = JSON.stringify([pairs, activePairKey]);
  if (container.dataset.renderKey === renderKey) return;
  closePairPicker(container, pickerState);
  container.dataset.renderKey = renderKey;
  const groups = groupProductPairs(pairs);
  const active = pairs.find((pair) => pair.key === activePairKey);
  if (!active) { container.replaceChildren(element("p", "", "暂无有报告的商品")); return; }
  const group = groups.find((item) => item.id === active.selfSpu);
  const selfArea = element("section", "product-select-self");
  selfArea.append(element("div", "product-select-label", "本品"), dropdown({
    container, pickerState, id: "pair-trigger", label: "切换本品", selected: group,
    items: groups.map((item) => ({ ...item, detail: `${item.competitors.length} 个有报告的竞品` })),
    onSelect: (item) => onPairChange(item.competitors[0].key), onBeforeOpen
  }));
  const compArea = element("section", "product-select-competitors");
  compArea.append(element("div", "product-select-label", `对比竞品 · ${group.competitors.length}`));
  if (group.competitors.length > 2) {
    compArea.append(dropdown({ container, pickerState, id: "competitor-trigger", label: "切换竞品",
      items: group.competitors.map((pair) => ({ ...competitorProduct(pair), key: pair.key })),
      selected: competitorProduct(active), onSelect: (item) => onPairChange(item.key), onBeforeOpen, searchable: true
    }));
  } else {
    const cards = element("div", "product-select-cards");
    for (const pair of group.competitors) {
      const product = competitorProduct(pair);
      const card = element("div", "product-select-card-wrap");
      const button = element("button", "product-select-card");
      button.type = "button";
      button.dataset.pairKey = pair.key;
      button.setAttribute("aria-label", `对比${product.name || product.id}`);
      button.setAttribute("aria-pressed", String(pair.key === activePairKey));
      button.append(productContent(product), element("span", "product-select-check", pair.key === activePairKey ? "✓" : ""));
      button.onclick = () => {
        closePairPicker(container, pickerState);
        onPairChange(pair.key);
        [...container.querySelectorAll("[data-pair-key]")].find((item) => item.dataset.pairKey === pair.key)?.focus();
      };
      card.append(button, jdLink(product));
      cards.append(card);
    }
    compArea.append(cards);
  }
  container.replaceChildren(selfArea, element("span", "product-select-vs", "VS"), compArea);
}
