const sampleReport = {
  date: "2026年8月17日",
  granularity: "日",
  selfProduct: {
    id: "100174558585",
    name: "小彩绘奇遇雨衣",
    imageUrl: "https://img10.360buyimg.com/pcpubliccms/s1440x1440_jfs/t1/395267/36/3454/188468/6986d6b1F58ad5ae5/00832ee3e8d3f891.jpg.avif"
  },
  competitorProduct: {
    id: "100112260075",
    name: "牧萌儿童雨衣男女童带书包位防水透气宝宝"
  }
};

const optionDefinitions = [
  {
    id: "a",
    label: "方案 A",
    name: "紧凑工具栏",
    description: "商品、日期和操作保持在一行，信息完整但占用高度较少。",
    render: renderCompactToolbar
  },
  {
    id: "b",
    label: "方案 B",
    name: "商品主导",
    description: "商品关系最醒目，筛选项收在下方，适合强调本品与竞品。",
    render: renderProductFirst
  },
  {
    id: "c",
    label: "方案 C",
    name: "筛选主导",
    description: "先选择商品对和日期，再用一行摘要确认当前分析对象。",
    render: renderFilterFirst
  },
  {
    id: "d",
    label: "方案 D",
    name: "双栏信息板",
    description: "左侧集中展示对比关系，右侧形成独立且稳定的操作区。",
    render: renderSplitBoard
  },
  {
    id: "e",
    label: "方案 E",
    name: "极简摘要条",
    description: "去掉商品卡片，只保留业务判断所需的核心信息与操作。",
    render: renderMinimalStrip
  }
];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function productAvatar(product, role, size = "regular") {
  const image = product.imageUrl
    ? `<img src="${escapeHtml(product.imageUrl)}" alt="${escapeHtml(product.name)}主图" referrerpolicy="no-referrer">`
    : `<span class="avatar-placeholder" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 5.5h16v13H4zM7.5 15l3.1-3.4 2.4 2.5 1.7-1.7 2.8 2.6M16.5 8.7h.01"/></svg><span>暂无主图</span></span>`;
  return `<span class="product-avatar product-avatar-${size} product-avatar-${role}">${image}</span>`;
}

function productSummary(product, role, options = {}) {
  const label = role === "self" ? "本品" : "竞品";
  const compactClass = options.compact ? " product-summary-compact" : "";
  return `
    <article class="product-summary${compactClass}">
      ${productAvatar(product, role, options.compact ? "small" : "regular")}
      <span class="product-copy">
        <span class="product-heading">
          <span class="role-tag role-tag-${role}">${label}</span>
          <strong title="${escapeHtml(product.name)}">${escapeHtml(product.name)}</strong>
        </span>
        <span class="product-id">商品 ID ${escapeHtml(product.id)}</span>
      </span>
    </article>`;
}

function pairSelect(extraClass = "") {
  return `
    <label class="field-control ${extraClass}">
      <span class="field-label">商品对</span>
      <span class="select-wrap">
        <select aria-label="商品对">
          <option>${escapeHtml(sampleReport.selfProduct.name)} vs ${escapeHtml(sampleReport.competitorProduct.name)}</option>
        </select>
      </span>
    </label>`;
}

function dateControl(extraClass = "") {
  return `
    <label class="field-control ${extraClass}">
      <span class="field-label">分析周期</span>
      <button class="date-button" type="button">
        <span class="calendar-icon" aria-hidden="true"></span>
        <span>${escapeHtml(sampleReport.date)}</span>
        <span class="chevron" aria-hidden="true"></span>
      </button>
    </label>`;
}

function skuControl(label = "查看 SKU") {
  return `
    <span class="field-control sku-field">
      <span class="field-label">本品组成</span>
      <button class="secondary-button" type="button">${escapeHtml(label)}</button>
    </span>`;
}

function reportMeta() {
  return `<span class="report-meta"><strong>${escapeHtml(sampleReport.date)}</strong><i aria-hidden="true"></i>分析粒度：${escapeHtml(sampleReport.granularity)}</span>`;
}

function renderCompactToolbar() {
  return `
    <section class="preview preview-a" aria-label="紧凑工具栏预览">
      <div class="compact-pair">
        <div class="compact-avatars" aria-hidden="true">
          ${productAvatar(sampleReport.selfProduct, "self", "tiny")}
          ${productAvatar(sampleReport.competitorProduct, "competitor", "tiny")}
        </div>
        <div class="compact-pair-copy">
          <span class="compact-title">${escapeHtml(sampleReport.selfProduct.name)} <b>VS</b> ${escapeHtml(sampleReport.competitorProduct.name)}</span>
          ${reportMeta()}
        </div>
      </div>
      <div class="compact-controls">
        ${pairSelect("compact-pair-select")}
        ${dateControl("compact-date")}
        ${skuControl()}
      </div>
    </section>`;
}

function renderProductFirst() {
  return `
    <section class="preview preview-b" aria-label="商品主导预览">
      <div class="product-first-top">
        ${reportMeta()}
        <span class="report-state"><i aria-hidden="true"></i>当前报告</span>
      </div>
      <div class="large-comparison">
        ${productSummary(sampleReport.selfProduct, "self")}
        <span class="versus-badge" aria-hidden="true">VS</span>
        ${productSummary(sampleReport.competitorProduct, "competitor")}
      </div>
      <div class="product-first-controls">
        ${pairSelect()}
        ${dateControl()}
        ${skuControl("查看 18 个 SKU")}
      </div>
    </section>`;
}

function renderFilterFirst() {
  return `
    <section class="preview preview-c" aria-label="筛选主导预览">
      <div class="filter-first-title">
        <div>
          <span class="section-kicker">当前分析范围</span>
          <strong>报告筛选</strong>
        </div>
        <span class="granularity-tag">按日分析</span>
      </div>
      <div class="filter-first-controls">
        ${pairSelect()}
        ${dateControl()}
        ${skuControl()}
      </div>
      <div class="pair-summary-line">
        <span class="pair-side"><span class="role-tag role-tag-self">本品</span><strong>${escapeHtml(sampleReport.selfProduct.name)}</strong><small>${escapeHtml(sampleReport.selfProduct.id)}</small></span>
        <span class="direction-arrow" aria-hidden="true">→</span>
        <span class="pair-side"><span class="role-tag role-tag-competitor">竞品</span><strong>${escapeHtml(sampleReport.competitorProduct.name)}</strong><small>${escapeHtml(sampleReport.competitorProduct.id)}</small></span>
      </div>
    </section>`;
}

function renderSplitBoard() {
  return `
    <section class="preview preview-d" aria-label="双栏信息板预览">
      <div class="split-product-panel">
        <div class="split-panel-heading">
          <span>当前商品对</span>
          ${reportMeta()}
        </div>
        <div class="split-comparison">
          ${productSummary(sampleReport.selfProduct, "self", { compact: true })}
          <span class="split-divider"><i></i><b>VS</b><i></i></span>
          ${productSummary(sampleReport.competitorProduct, "competitor", { compact: true })}
        </div>
      </div>
      <aside class="split-control-panel">
        ${pairSelect()}
        <div class="split-control-row">
          ${dateControl()}
          ${skuControl("SKU 明细")}
        </div>
      </aside>
    </section>`;
}

function renderMinimalStrip() {
  return `
    <section class="preview preview-e" aria-label="极简摘要条预览">
      <div class="minimal-context">
        <span class="minimal-date">${escapeHtml(sampleReport.date)}</span>
        <span class="granularity-pill">日</span>
      </div>
      <div class="minimal-pair" title="${escapeHtml(sampleReport.selfProduct.name)} VS ${escapeHtml(sampleReport.competitorProduct.name)}">
        <span class="minimal-side minimal-side-self"><b>本品</b>${escapeHtml(sampleReport.selfProduct.name)}</span>
        <span class="minimal-vs">VS</span>
        <span class="minimal-side"><b>竞品</b>${escapeHtml(sampleReport.competitorProduct.name)}</span>
      </div>
      <div class="minimal-actions">
        <button class="icon-text-button" type="button"><span class="swap-icon" aria-hidden="true">⇄</span>切换商品对</button>
        <button class="icon-text-button" type="button"><span class="calendar-icon" aria-hidden="true"></span>切换日期</button>
        <button class="primary-button" type="button">查看 SKU</button>
      </div>
    </section>`;
}

/**
 * 功能说明：使用同一份报告示例数据渲染全部头部方案，并绑定方案选择状态。
 * 参数 options：方案定义数组，包含标识、名称、说明和渲染函数。
 * 参数 target：承载全部方案卡片的页面节点。
 * 返回值：无；直接写入 Playground 页面并注册选择事件。
 */
function renderOptions(options, target) {
  target.innerHTML = options.map((option) => `
    <article class="option-card" id="option-${option.id}" data-option="${option.id}">
      <header class="option-header">
        <div class="option-heading">
          <span class="option-label">${option.label}</span>
          <div>
            <h2>${option.name}</h2>
            <p>${option.description}</p>
          </div>
        </div>
        <button class="choose-button" type="button" data-choose="${option.id}" aria-pressed="false">选择此方案</button>
      </header>
      ${option.render()}
    </article>`).join("");

  target.addEventListener("click", (event) => {
    const button = event.target.closest("[data-choose]");
    if (!button) {
      return;
    }
    const selectedId = button.dataset.choose;
    const selectedOption = options.find((option) => option.id === selectedId);
    target.querySelectorAll("[data-option]").forEach((card) => {
      const selected = card.dataset.option === selectedId;
      card.classList.toggle("is-selected", selected);
      const chooseButton = card.querySelector("[data-choose]");
      chooseButton.setAttribute("aria-pressed", String(selected));
      chooseButton.textContent = selected ? "已选择" : "选择此方案";
    });
    const output = document.querySelector("#selection-output");
    output.textContent = `当前选择：${selectedOption.label} · ${selectedOption.name}`;
    output.classList.add("has-selection");
  });
}

renderOptions(optionDefinitions, document.querySelector("#options"));
