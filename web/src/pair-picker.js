import { groupProductPairs } from "./report-selection.js";
import "./product-picker.css";

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function productContent(product, role = "self") {
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
  const heading = element("span", "product-select-heading");
  const name = element("strong", "", product.name || product.id);
  name.title = name.textContent;
  heading.append(element("span", `product-role product-role-${role}`, role === "self" ? "本品" : "竞品"), name);
  copy.append(heading, element("small", "", `商品 ID ${product.id}`));
  wrapper.append(frame, copy);
  return wrapper;
}

function jdLink(product, role) {
  const link = element("a", "product-select-link");
  link.href = `https://item.jd.com/${encodeURIComponent(product.id)}.html`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `在京东打开${product.name || product.id}`);
  link.append(productContent(product, role));
  return link;
}

/**
 * 功能说明：关闭本品菜单，并按需恢复按钮焦点。
 * 参数 container：商品选择区根节点。
 * 参数 pickerState：菜单开合状态。
 * 参数 restoreFocus：是否恢复本品切换按钮焦点。
 * 返回值：关闭了打开的菜单时返回 true，否则返回 false。
 */
export function closePairPicker(container, pickerState, restoreFocus = false) {
  if (!container || !pickerState.open) return false;
  pickerState.open = false;
  container.querySelector(".product-select-menu").hidden = true;
  const trigger = container.querySelector("#pair-trigger");
  trigger.setAttribute("aria-expanded", "false");
  if (restoreFocus) trigger.focus();
  return true;
}

/**
 * 功能说明：构造有主图的本品菜单，支持选中标记、方向键和 Esc。
 * 参数 container：商品选择区，供菜单关闭和焦点恢复使用。
 * 参数 groups：由已有报告去重得到的本品及关联竞品。
 * 参数 selected：当前本品分组。
 * 参数 pickerState：页面共享菜单状态。
 * 参数 onBeforeOpen：打开前关闭日历的回调。
 * 参数 onPairChange：切换本品后选中关联商品对的回调。
 * 返回值：本品商品块 DOM。
 */
function selfPicker(container, groups, selected, pickerState, onBeforeOpen, onPairChange) {
  const root = element("div", "product-select-item product-select-dropdown");
  const trigger = element("button", "product-select-card");
  trigger.type = "button";
  trigger.id = "pair-trigger";
  trigger.setAttribute("aria-label", "切换本品");
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  trigger.setAttribute("aria-controls", "pair-trigger-list");
  trigger.append(element("span", "product-select-marker", "⌄"));
  const menu = element("div", "product-select-menu");
  menu.hidden = true;
  const list = element("div", "product-select-list");
  list.id = "pair-trigger-list";
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", "选择本品");
  for (const group of groups) {
    const option = element("button", "product-select-option");
    option.type = "button";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(group.id === selected.id));
    option.append(productContent(group), element("span", "product-select-check", group.id === selected.id ? "✓" : ""));
    option.onclick = (event) => {
      event.stopPropagation();
      closePairPicker(container, pickerState, true);
      if (group.id !== selected.id) onPairChange(group.competitors[0].key);
      container.querySelector("#pair-trigger")?.focus();
    };
    list.append(option);
  }
  menu.append(list);
  const open = () => {
    onBeforeOpen?.();
    pickerState.open = true;
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    (list.querySelector('[aria-selected="true"]') || list.querySelector("button"))?.focus();
  };
  trigger.onclick = () => menu.hidden ? open() : closePairPicker(container, pickerState);
  trigger.onkeydown = (event) => {
    if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); open(); }
  };
  menu.onkeydown = (event) => {
    if (event.key === "Escape") { event.preventDefault(); closePairPicker(container, pickerState, true); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const options = [...list.querySelectorAll("button")];
    const index = options.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
      : Math.max(0, Math.min(options.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
    options[next]?.focus();
  };
  root.append(trigger, jdLink(selected, "self"), menu);
  return root;
}

/**
 * 功能说明：渲染紧凑本品与竞品商品块，商品链接与分析切换操作独立。
 * 参数 options：包含 container 根节点、pairs 已有报告商品对、activePairKey 当前商品对、
 * pickerState 菜单状态、onBeforeOpen 打开前回调、onPairChange 商品对切换回调。
 * 返回值：无，更新选择区 DOM；相同数据不重建菜单。
 */
export function renderPairPicker(options) {
  const { container, pairs, activePairKey, pickerState, onBeforeOpen, onPairChange } = options;
  const renderKey = JSON.stringify([pairs, activePairKey]);
  if (container.dataset.renderKey === renderKey) return;
  closePairPicker(container, pickerState);
  container.dataset.renderKey = renderKey;
  const groups = groupProductPairs(pairs);
  const active = pairs.find((pair) => pair.key === activePairKey);
  if (!active) { container.replaceChildren(element("p", "", "暂无有报告的商品")); return; }
  const group = groups.find((item) => item.id === active.selfSpu);
  // 正常业务是一至两个竞品；额外记录换行展示，不隐藏已有报告。
  container.style.setProperty("--product-columns", Math.min(3, group.competitors.length + 1));
  const children = [selfPicker(container, groups, group, pickerState, onBeforeOpen, onPairChange)];
  for (const pair of group.competitors) {
    const product = { id: pair.competitorSpu, name: pair.competitorName, imageUrl: pair.competitorImageUrl };
    const selected = pair.key === activePairKey;
    const card = element("div", `product-select-item${selected ? " is-selected" : ""}`);
    const button = element("button", "product-select-card");
    button.type = "button";
    button.dataset.pairKey = pair.key;
    button.setAttribute("aria-label", `对比${product.name || product.id}`);
    button.setAttribute("aria-pressed", String(selected));
    button.append(element("span", "product-select-marker", selected ? "✓" : "○"));
    button.onclick = () => {
      closePairPicker(container, pickerState);
      onPairChange(pair.key);
      [...container.querySelectorAll("[data-pair-key]")].find((item) => item.dataset.pairKey === pair.key)?.focus();
    };
    card.append(button, jdLink(product, "competitor"));
    children.push(card);
  }
  container.replaceChildren(...children);
}
