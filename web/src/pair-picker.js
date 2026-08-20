function productImage(product, label) {
  const frame = document.createElement("span");
  frame.className = "pair-option-image";
  if (product.imageUrl) {
    const image = document.createElement("img");
    image.src = product.imageUrl;
    image.alt = `${product.name || label}主图`;
    image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => {
      image.remove();
      frame.classList.add("is-placeholder");
      frame.textContent = "暂无主图";
    }, { once: true });
    frame.append(image);
    return frame;
  }
  frame.classList.add("is-placeholder");
  frame.textContent = "暂无主图";
  return frame;
}

function productDetails(product, label, role) {
  const wrapper = document.createElement("span");
  wrapper.className = "pair-option-product";
  wrapper.append(productImage(product, label));

  const copy = document.createElement("span");
  copy.className = "pair-option-product-copy";
  const heading = document.createElement("span");
  heading.className = `product-role product-role-${role}`;
  heading.textContent = label;
  const name = document.createElement("strong");
  name.textContent = product.name || `${label} ${product.id}`;
  name.title = name.textContent;
  const id = document.createElement("small");
  id.textContent = `商品 ID ${product.id}`;
  copy.append(heading, name, id);
  wrapper.append(copy);
  return wrapper;
}

function createPairOption(pair, activePairKey, onPairChange) {
  const button = document.createElement("button");
  const selected = pair.key === activePairKey;
  button.type = "button";
  button.className = `pair-option${selected ? " is-selected" : ""}`;
  button.dataset.pairKey = pair.key;
  button.setAttribute("role", "option");
  button.setAttribute("aria-selected", String(selected));
  button.append(
    productDetails(
      { id: pair.selfSpu, name: pair.selfName, imageUrl: pair.selfImageUrl },
      "本品",
      "self"
    )
  );
  const marker = document.createElement("span");
  marker.className = "pair-option-marker";
  marker.textContent = "VS";
  marker.setAttribute("aria-hidden", "true");
  button.append(marker);
  button.append(
    productDetails(
      {
        id: pair.competitorSpu,
        name: pair.competitorName,
        imageUrl: pair.competitorImageUrl
      },
      "竞品",
      "competitor"
    )
  );
  const check = document.createElement("span");
  check.className = "pair-option-check";
  check.textContent = selected ? "✓" : "";
  check.setAttribute("aria-hidden", "true");
  button.append(check);
  button.addEventListener("click", () => onPairChange(pair.key));
  return button;
}

function syncPickerState(container, pickerState) {
  const trigger = container.querySelector("#pair-trigger");
  const popover = container.querySelector("#pair-popover");
  trigger?.setAttribute("aria-expanded", String(pickerState.open));
  container.classList.toggle("is-open", pickerState.open);
  if (popover) {
    popover.classList.toggle("is-open", pickerState.open);
    popover.classList.toggle("is-closing", pickerState.closing);
    popover.classList.toggle("is-entering", pickerState.animateOpen);
    popover.hidden = !pickerState.open && !pickerState.closing;
  }
}

function focusPairOption(container, position) {
  const options = [...container.querySelectorAll(".pair-option")];
  if (!options.length) {
    return;
  }
  const currentIndex = options.indexOf(document.activeElement);
  let nextIndex = currentIndex;
  if (position === "first") nextIndex = 0;
  if (position === "last") nextIndex = options.length - 1;
  if (position === "next") nextIndex = Math.min(options.length - 1, Math.max(0, currentIndex + 1));
  if (position === "previous") nextIndex = Math.max(0, currentIndex <= 0 ? 0 : currentIndex - 1);
  options[nextIndex]?.focus();
}

/**
 * 功能说明：关闭商品对下拉框，并按需把焦点还给触发区域。
 * 参数 container：商品对选择器根节点。
 * 参数 pickerState：包含 open 状态的选择器状态对象。
 * 参数 restoreFocus：是否在关闭后聚焦商品对触发按钮。
 * 返回值：下拉框原本打开并成功关闭时返回 true，否则返回 false。
 */
export function closePairPicker(container, pickerState, restoreFocus = false) {
  if (!container || !pickerState.open) {
    return false;
  }
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  pickerState.open = false;
  pickerState.animateOpen = false;
  pickerState.closing = !reduceMotion;
  syncPickerState(container, pickerState);
  if (restoreFocus) {
    container.querySelector("#pair-trigger")?.focus();
  }
  return true;
}

/**
 * 功能说明：渲染可展示商品主图的商品对下拉框，并绑定鼠标与键盘切换交互。
 * 参数 options：包含根节点、商品对列表、当前商品对、开合状态和切换回调。
 * 返回值：无；直接更新商品对触发区域和下拉列表。
 */
export function renderPairPicker(options) {
  const { container, pairs, activePairKey, pickerState, onBeforeOpen, onPairChange } = options;
  const panel = container.querySelector(".pair-panel");
  const trigger = container.querySelector("#pair-trigger");
  const popover = container.querySelector("#pair-popover");
  trigger.disabled = !pairs.length;
  popover.replaceChildren(...pairs.map((pair) => createPairOption(pair, activePairKey, (pairKey) => {
    pickerState.open = false;
    pickerState.closing = false;
    pickerState.animateOpen = false;
    syncPickerState(container, pickerState);
    onPairChange(pairKey);
  })));
  syncPickerState(container, pickerState);

  const openPicker = (focusOption = false) => {
    if (!pairs.length) {
      return;
    }
    onBeforeOpen?.();
    pickerState.open = true;
    pickerState.closing = false;
    pickerState.animateOpen = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    syncPickerState(container, pickerState);
    if (focusOption) {
      requestAnimationFrame(() => {
        const selected = popover.querySelector(".pair-option.is-selected");
        (selected || popover.querySelector(".pair-option"))?.focus();
      });
    }
  };

  trigger.onclick = () => {
    if (pickerState.open) {
      closePairPicker(container, pickerState);
      return;
    }
    openPicker();
  };
  trigger.onkeydown = (event) => {
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    openPicker(true);
  };
  panel.onclick = (event) => {
    if (event.target.closest("#pair-trigger, a.product-card, .pair-popover")) {
      return;
    }
    trigger.click();
  };
  popover.onkeydown = (event) => {
    const actions = {
      ArrowDown: "next",
      ArrowUp: "previous",
      Home: "first",
      End: "last"
    };
    if (actions[event.key]) {
      event.preventDefault();
      focusPairOption(container, actions[event.key]);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closePairPicker(container, pickerState, true);
    }
  };
  popover.onanimationend = (event) => {
    if (event.animationName === "period-picker-fold-enter") {
      pickerState.animateOpen = false;
      popover.classList.remove("is-entering");
      return;
    }
    if (event.animationName === "period-picker-fold-exit" && pickerState.closing) {
      pickerState.closing = false;
      syncPickerState(container, pickerState);
    }
  };
}
