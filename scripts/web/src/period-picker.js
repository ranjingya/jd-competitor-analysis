const granularityLabels = { day: "日", week: "周", month: "月" };
const weekdayLabels = ["一", "二", "三", "四", "五", "六", "日"];

function reportsFor(index, granularity) {
  return index?.reports?.[granularity] || [];
}

function dateParts(value) {
  const [year, month, day] = String(value).split("-").map(Number);
  return { year, month, day };
}

function utcDate(value) {
  const { year, month, day } = dateParts(value);
  return new Date(Date.UTC(year, month - 1, day));
}

function isoDate(date) {
  return [date.getUTCFullYear(), String(date.getUTCMonth() + 1).padStart(2, "0"), String(date.getUTCDate()).padStart(2, "0")].join("-");
}

function formatDayLabel(value, includeYear = true) {
  const { year, month, day } = dateParts(value);
  return `${includeYear ? `${year}年` : ""}${month}月${day}日`;
}

function formatWeekRange(start, end) {
  const from = dateParts(start);
  const to = dateParts(end);
  if (from.year !== to.year) return `${formatDayLabel(start)}—${formatDayLabel(end)}`;
  if (from.month !== to.month) return `${formatDayLabel(start)}—${formatDayLabel(end, false)}`;
  return `${formatDayLabel(start)}—${to.day}日`;
}

function formatPeriodLabel(granularity, entry) {
  if (!entry) return "暂无可用报告";
  if (granularity === "day") return formatDayLabel(entry.period_start);
  if (granularity === "week") return formatWeekRange(entry.period_start, entry.period_end);
  const { year, month } = dateParts(entry.period_start);
  return `${year}年${month}月`;
}

function isCrossMonth(entry) {
  const from = dateParts(entry.period_start);
  const to = dateParts(entry.period_end);
  return from.year !== to.year || from.month !== to.month;
}

function isoWeekNumber(value) {
  const date = utcDate(value);
  const weekday = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - weekday);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  return Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
}

function datesInRange(start, end) {
  const dates = [];
  const cursor = utcDate(start);
  const finalDate = utcDate(end);
  while (cursor <= finalDate) {
    dates.push(isoDate(cursor));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return dates;
}

function calendarWeeks(year, month) {
  const first = new Date(Date.UTC(year, month - 1, 1));
  const last = new Date(Date.UTC(year, month, 0));
  const firstOffset = (first.getUTCDay() + 6) % 7;
  const lastOffset = 7 - (last.getUTCDay() || 7);
  first.setUTCDate(first.getUTCDate() - firstOffset);
  last.setUTCDate(last.getUTCDate() + lastOffset);
  const dates = datesInRange(isoDate(first), isoDate(last));
  return Array.from({ length: dates.length / 7 }, (_, index) => dates.slice(index * 7, index * 7 + 7));
}

function selectedEntry(options, granularity = options.activeGranularity) {
  const reports = reportsFor(options.index, granularity);
  const selectedKey = options.selectedPeriods[granularity];
  return reports.find((entry) => entry.period_key === selectedKey) || reports.at(-1) || null;
}

function contextForEntry(granularity, entry) {
  if (!entry) return "";
  return granularity === "month" ? entry.period_start.slice(0, 4) : entry.period_start.slice(0, 7);
}

function availableContexts(options, granularity) {
  return [...new Set(reportsFor(options.index, granularity).map((entry) => contextForEntry(granularity, entry)))].filter(Boolean).sort();
}

function activeContext(options, granularity) {
  const contexts = availableContexts(options, granularity);
  const selectedContext = contextForEntry(granularity, selectedEntry(options, granularity));
  const current = options.pickerState.contexts[granularity];
  if (!contexts.includes(current)) options.pickerState.contexts[granularity] = selectedContext || contexts.at(-1) || "";
  return options.pickerState.contexts[granularity];
}

function weekdayHeader() {
  return `<div class="period-weekday-row">${weekdayLabels.map((label) => `<span>${label}</span>`).join("")}</div>`;
}

/**
 * 功能说明：生成日历头部，并按当前有数据的月份或年份绑定前后导航。
 * 参数 options：周期选择器渲染配置与回调。
 * 参数 granularity：day、week 或 month。
 * 参数 title：当前年月标题。
 * 参数 note：当前选择方式说明。
 * 返回值：日历头部 HTML 字符串。
 */
function calendarHeader(options, granularity, title, note) {
  const contexts = availableContexts(options, granularity);
  const context = activeContext(options, granularity);
  const index = contexts.indexOf(context);
  return `
    <header class="period-calendar-header">
      <button type="button" data-context-index="${index - 1}" aria-label="上一个可用周期" ${index <= 0 ? "disabled" : ""}>‹</button>
      <div><strong>${title}</strong><span>${note}</span></div>
      <button type="button" data-context-index="${index + 1}" aria-label="下一个可用周期" ${index < 0 || index >= contexts.length - 1 ? "disabled" : ""}>›</button>
    </header>
  `;
}

function bindContextNavigation(root, options, granularity) {
  const contexts = availableContexts(options, granularity);
  root.querySelectorAll("[data-context-index]:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => {
      options.pickerState.contexts[granularity] = contexts[Number(button.dataset.contextIndex)];
      options.pickerState.animateOpen = false;
      renderPeriodPicker(options);
    });
  });
}

function createDayPanel(options) {
  const context = activeContext(options, "day");
  const [year, month] = context.split("-").map(Number);
  const root = document.createElement("div");
  root.className = "period-calendar-panel";
  const selected = selectedEntry(options, "day");
  const available = new Map(reportsFor(options.index, "day").map((entry) => [entry.period_start, entry]));
  root.innerHTML = `
    ${calendarHeader(options, "day", `${year} 年 ${month} 月`, "选择单日报告")}
    ${weekdayHeader()}
    <div class="period-day-grid">
      ${calendarWeeks(year, month).flat().map((date) => {
        const parts = dateParts(date);
        const entry = available.get(date);
        const outside = parts.month !== month;
        return `<button type="button" data-period-key="${entry?.period_key || ""}" class="period-day-cell${outside ? " is-outside" : ""}${entry ? " has-report" : ""}${entry?.period_key === selected?.period_key ? " is-selected" : ""}" ${entry ? "" : "disabled"} aria-pressed="${entry?.period_key === selected?.period_key}"><span>${outside ? `${parts.month}/${parts.day}` : parts.day}</span></button>`;
      }).join("")}
    </div>
  `;
  bindContextNavigation(root, options, "day");
  bindPeriodSelection(root, options, "day");
  return root;
}

function createWeekPanel(options) {
  const context = activeContext(options, "week");
  const [year, month] = context.split("-").map(Number);
  const root = document.createElement("div");
  root.className = "period-calendar-panel period-week-panel";
  const selected = selectedEntry(options, "week");
  const available = new Map(reportsFor(options.index, "week").map((entry) => [entry.period_start, entry]));
  root.innerHTML = `
    ${calendarHeader(options, "week", `${year} 年 ${month} 月`, "选择完整自然周")}
    ${weekdayHeader()}
    <div class="period-week-grid">
      ${calendarWeeks(year, month).map((dates) => {
        const entry = available.get(dates[0]);
        const isSelected = entry?.period_key === selected?.period_key;
        return `
        <button type="button" class="period-week-row${isSelected ? " is-selected" : ""}" data-period-key="${entry?.period_key || ""}" ${entry ? "" : "disabled"} aria-pressed="${isSelected}" ${entry ? `aria-label="第 ${isoWeekNumber(entry.period_start)} 周，${formatWeekRange(entry.period_start, entry.period_end)}"` : ""}>
          ${dates.map((date) => {
            const parts = dateParts(date);
            const outside = parts.month !== month;
            return `<span class="period-week-day${outside ? " is-outside" : ""}"><b>${outside ? `${parts.month}/${parts.day}` : parts.day}</b></span>`;
          }).join("")}
        </button>
      `;
      }).join("")}
    </div>
    ${selected ? `<footer class="period-week-summary"><span>第 ${isoWeekNumber(selected.period_start)} 周${isCrossMonth(selected) ? " · 跨月" : ""}</span><strong>${formatWeekRange(selected.period_start, selected.period_end)}</strong></footer>` : ""}
  `;
  bindContextNavigation(root, options, "week");
  bindPeriodSelection(root, options, "week");
  return root;
}

function createMonthPanel(options) {
  const context = activeContext(options, "month");
  const year = Number(context);
  const root = document.createElement("div");
  root.className = "period-calendar-panel period-month-panel";
  const selected = selectedEntry(options, "month");
  const entries = reportsFor(options.index, "month").filter((entry) => entry.period_start.startsWith(`${context}-`));
  root.innerHTML = `
    ${calendarHeader(options, "month", `${year} 年`, "选择整月报告")}
    <div class="period-month-grid">
      ${Array.from({ length: 12 }, (_, index) => {
        const month = index + 1;
        const entry = entries.find((item) => Number(item.period_start.slice(5, 7)) === month);
        return `<button type="button" data-period-key="${entry?.period_key || ""}" ${entry ? "" : "disabled"} class="period-month-cell${entry?.period_key === selected?.period_key ? " is-selected" : ""}" aria-pressed="${entry?.period_key === selected?.period_key}"><strong>${String(month).padStart(2, "0")}</strong><span>${entry ? "报告可用" : "暂无报告"}</span></button>`;
      }).join("")}
    </div>
  `;
  bindContextNavigation(root, options, "month");
  bindPeriodSelection(root, options, "month");
  return root;
}

function bindPeriodSelection(root, options, granularity) {
  root.querySelectorAll("[data-period-key]:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => {
      const entry = reportsFor(options.index, granularity).find((item) => item.period_key === button.dataset.periodKey);
      if (!entry) return;
      options.pickerState.contexts[granularity] = contextForEntry(granularity, entry);
      options.pickerState.open = true;
      options.pickerState.closing = false;
      options.pickerState.animateOpen = false;
      options.onPeriodChange(granularity, entry.period_key);
    });
  });
}

function createActivePanel(options, granularity) {
  if (granularity === "week") return createWeekPanel(options);
  if (granularity === "month") return createMonthPanel(options);
  return createDayPanel(options);
}

/**
 * 功能说明：切换日、周视图时优先沿用当前月份，确保日期网格保持在原位置。
 * 参数 options：周期选择器渲染配置与各粒度上下文。
 * 参数 currentGranularity：切换前的粒度。
 * 参数 nextGranularity：即将切换到的粒度。
 * 返回值：目标粒度应显示的月份或年份上下文。
 */
function contextAfterGranularitySwitch(options, currentGranularity, nextGranularity) {
  const currentContext = activeContext(options, currentGranularity);
  const nextContexts = availableContexts(options, nextGranularity);
  const switchesCalendarMode = ["day", "week"].includes(currentGranularity) && ["day", "week"].includes(nextGranularity);
  if (switchesCalendarMode && nextContexts.includes(currentContext)) {
    return currentContext;
  }
  return contextForEntry(nextGranularity, selectedEntry(options, nextGranularity));
}

/**
 * 功能说明：播放周期选择器的收起动效，并同步按钮的可访问状态。
 * 参数 container：周期选择器容器元素。
 * 参数 pickerState：周期选择器的开合与动效状态。
 * 返回值：成功发起收起时返回 true，否则返回 false。
 */
export function closePeriodPicker(container, pickerState) {
  if (!container || !pickerState.open) return false;
  const trigger = container.querySelector("#period-trigger");
  const popover = container.querySelector("#period-popover");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  pickerState.open = false;
  pickerState.animateOpen = false;
  trigger?.setAttribute("aria-expanded", "false");
  if (!popover || reduceMotion) {
    pickerState.closing = false;
    popover?.classList.remove("is-open", "is-entering", "is-closing");
    return true;
  }
  pickerState.closing = true;
  popover.classList.remove("is-open", "is-entering");
  popover.classList.add("is-closing");
  return true;
}

/**
 * 功能说明：渲染日、周、月一体化周期选择器，并绑定粒度、周期与月份导航交互。
 * 参数 options：包含容器、报告索引、当前粒度、已选周期、弹层状态与变更回调。
 * 返回值：无。
 */
export function renderPeriodPicker(options) {
  const activeEntry = selectedEntry(options, options.activeGranularity);
  const pickerGranularity = options.pickerState.open
    ? options.pickerState.draftGranularity || options.activeGranularity
    : options.activeGranularity;
  const pickerEntry = selectedEntry(options, pickerGranularity);
  options.container.innerHTML = `
    <label class="period-label" for="period-trigger">分析周期</label>
    <button class="period-trigger" id="period-trigger" type="button" aria-expanded="${options.pickerState.open}" aria-controls="period-popover" ${activeEntry ? "" : "disabled"}>
      <span class="period-calendar-icon" aria-hidden="true">▦</span>
      <span>${formatPeriodLabel(options.activeGranularity, activeEntry)}</span>
      <span class="period-chevron" aria-hidden="true"></span>
    </button>
    <div class="period-popover${options.pickerState.open ? " is-open" : ""}${options.pickerState.closing ? " is-closing" : ""}${options.pickerState.animateOpen ? " is-entering" : ""}" id="period-popover">
      <nav class="period-granularity-rail" aria-label="分析粒度">
        ${Object.entries(granularityLabels).map(([key, label]) => {
          const count = reportsFor(options.index, key).length;
          return `<button type="button" data-granularity="${key}" class="${key === pickerGranularity ? "is-selected" : ""}" aria-pressed="${key === pickerGranularity}" ${count ? "" : "disabled"}><strong>${label}</strong><span>${count}</span></button>`;
        }).join("")}
      </nav>
      <section class="period-selector-content" data-selector-content></section>
    </div>
  `;
  options.container.querySelector("#period-trigger")?.addEventListener("click", () => {
    if (options.pickerState.open) {
      closePeriodPicker(options.container, options.pickerState);
      return;
    }
    options.pickerState.open = true;
    options.pickerState.closing = false;
    options.pickerState.animateOpen = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    options.pickerState.draftGranularity = options.activeGranularity;
    options.pickerState.contexts[options.activeGranularity] = contextForEntry(options.activeGranularity, activeEntry);
    renderPeriodPicker(options);
  });
  options.container.querySelectorAll("[data-granularity]:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => {
      const granularity = button.dataset.granularity;
      const context = contextAfterGranularitySwitch(options, pickerGranularity, granularity);
      options.pickerState.draftGranularity = granularity;
      options.pickerState.contexts[granularity] = context;
      options.pickerState.open = true;
      options.pickerState.closing = false;
      options.pickerState.animateOpen = false;
      renderPeriodPicker(options);
    });
  });
  const popover = options.container.querySelector("#period-popover");
  popover?.addEventListener("animationend", (event) => {
    if (event.animationName === "period-picker-fold-enter") {
      options.pickerState.animateOpen = false;
      popover.classList.remove("is-entering");
      return;
    }
    if (event.animationName === "period-picker-fold-exit" && options.pickerState.closing) {
      options.pickerState.closing = false;
      popover.classList.remove("is-closing");
    }
  });
  const content = options.container.querySelector("[data-selector-content]");
  if (content && pickerEntry) content.replaceChildren(createActivePanel(options, pickerGranularity));
}
