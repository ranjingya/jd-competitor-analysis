import { loadReportIndex } from "./data-client.js";

const weekdayLabels = ["一", "二", "三", "四", "五", "六", "日"];
const granularityLabels = { day: "日", week: "周", month: "月" };

const state = {
  index: null,
  selectedDay: "2026-06-07",
  compactGranularity: "day",
  compactKeys: {},
  adaptiveGranularity: "day",
  adaptiveKeys: {}
};

function isoDate(year, month, day) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function availableDays() {
  return new Set((state.index?.reports?.day || []).map((entry) => entry.period_start));
}

function latestEntry(granularity) {
  return state.index?.reports?.[granularity]?.at(-1) || null;
}

function formatDayLabel(value) {
  const [year, month, day] = value.split("-");
  return `${year} 年 ${Number(month)} 月 ${Number(day)} 日`;
}

function dateParts(value) {
  const [year, month, day] = String(value).split("-").map(Number);
  return { year, month, day };
}

/**
 * 功能说明：把周起止日期格式化为易读范围，并保留跨月、跨年边界信息。
 * 参数 start：周开始日期，格式为 YYYY-MM-DD。
 * 参数 end：周结束日期，格式为 YYYY-MM-DD。
 * 返回值：适合界面展示的中文日期范围。
 */
function formatWeekRange(start, end) {
  const from = dateParts(start);
  const to = dateParts(end);
  if (from.year !== to.year) {
    return `${from.year}年${from.month}月${from.day}日—${to.year}年${to.month}月${to.day}日`;
  }
  if (from.month !== to.month) {
    return `${from.year}年${from.month}月${from.day}日—${to.month}月${to.day}日`;
  }
  return `${from.year}年${from.month}月${from.day}日—${to.day}日`;
}

function formatPeriodLabel(granularity, entry) {
  if (!entry) return "暂无报告";
  if (granularity === "day") return formatDayLabel(entry.period_start);
  if (granularity === "week") return formatWeekRange(entry.period_start, entry.period_end);
  const { year, month } = dateParts(entry.period_start);
  return `${year} 年 ${month} 月`;
}

function isCrossMonth(entry) {
  const from = dateParts(entry.period_start);
  const to = dateParts(entry.period_end);
  return from.year !== to.year || from.month !== to.month;
}

function weekScopeLabel(entries) {
  if (!entries.length) return "暂无周报告";
  const from = dateParts(entries[0].period_start);
  const to = dateParts(entries.at(-1).period_end);
  if (from.year !== to.year) return `${from.year}年${from.month}月—${to.year}年${to.month}月`;
  if (from.month !== to.month) return `${from.year}年${from.month}—${to.month}月`;
  return `${from.year}年${from.month}月`;
}

function isoWeekNumber(value) {
  const { year, month, day } = dateParts(value);
  const date = new Date(Date.UTC(year, month - 1, day));
  const weekday = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - weekday);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  return Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
}

/**
 * 功能说明：生成指定月份的日期单元数据，并补齐月首空位。
 * 参数 year：四位年份。
 * 参数 month：从 1 开始的月份。
 * 返回值：包含空位与实际日期的数组。
 */
function monthCells(year, month) {
  const firstWeekday = new Date(year, month - 1, 1).getDay();
  const leading = (firstWeekday + 6) % 7;
  const dayCount = new Date(year, month, 0).getDate();
  return [
    ...Array.from({ length: leading }, () => null),
    ...Array.from({ length: dayCount }, (_, index) => isoDate(year, month, index + 1))
  ];
}

/**
 * 功能说明：创建可复用的日维度月历，并绑定有效报告日期的选择事件。
 * 参数 selectedDay：当前选中的 ISO 日期。
 * 参数 onSelect：选择有效日期后的回调函数。
 * 参数 compact：是否使用紧凑尺寸。
 * 返回值：完成事件绑定的月历 DOM 元素。
 */
function createDayCalendar(selectedDay, onSelect, compact = false) {
  const root = document.createElement("div");
  root.className = `month-calendar${compact ? " month-calendar--compact" : ""}`;
  const available = availableDays();
  const cells = monthCells(2026, 6);
  root.innerHTML = `
    <header class="calendar-header">
      <button type="button" aria-label="上个月" disabled>‹</button>
      <strong>2026 年 6 月</strong>
      <button type="button" aria-label="下个月" disabled>›</button>
    </header>
    <div class="weekday-row">${weekdayLabels.map((label) => `<span>${label}</span>`).join("")}</div>
    <div class="day-grid">
      ${cells.map((date) => {
        if (!date) return '<span class="day-cell day-cell--empty"></span>';
        const enabled = available.has(date);
        const selected = date === selectedDay;
        const day = Number(date.slice(-2));
        return `<button class="day-cell${enabled ? " has-report" : ""}${selected ? " is-selected" : ""}" type="button" data-date="${date}" ${enabled ? "" : "disabled"} aria-pressed="${selected}"><span>${day}</span>${enabled ? "<i></i>" : ""}</button>`;
      }).join("")}
    </div>
    <footer class="calendar-legend"><span><i></i>已有分析报告</span><strong>${formatDayLabel(selectedDay)}</strong></footer>
  `;
  root.querySelectorAll("[data-date]:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => onSelect(button.dataset.date));
  });
  return root;
}

function updateSharedDay(date) {
  state.selectedDay = date;
  const entry = matchingEntry("day", date);
  if (entry) state.compactKeys.day = entry.period_key;
  document.querySelector("#shared-selection").textContent = `日分析 · ${formatDayLabel(date)}`;
  document.querySelectorAll("[data-selected-label]").forEach((node) => {
    node.textContent = date;
  });
  renderDayExamples();
  if (state.compactGranularity === "day") renderCompactExample();
  console.info("Playground 日报告选择完成", { date });
}

/**
 * 功能说明：刷新前三个日历方案，使它们共享同一个选中日期。
 * 返回值：无。
 */
function renderDayExamples() {
  document.querySelectorAll("[data-day-calendar-host]").forEach((host) => {
    const shouldRemainHidden = host.hasAttribute("hidden");
    host.replaceChildren(createDayCalendar(state.selectedDay, updateSharedDay));
    if (shouldRemainHidden) host.hidden = true;
  });

  const dates = [...availableDays()].sort();
  const rail = document.querySelector("[data-date-rail]");
  rail.innerHTML = dates.map((date) => {
    const weekday = weekdayLabels[new Date(`${date}T00:00:00`).getDay() === 0 ? 6 : new Date(`${date}T00:00:00`).getDay() - 1];
    return `<button type="button" data-rail-date="${date}" class="${date === state.selectedDay ? "is-selected" : ""}"><span>周${weekday}</span><strong>${Number(date.slice(-2))}</strong><i></i></button>`;
  }).join("");
  rail.querySelectorAll("[data-rail-date]").forEach((button) => {
    button.addEventListener("click", () => updateSharedDay(button.dataset.railDate));
  });
}

function matchingEntry(granularity, date) {
  return (state.index?.reports?.[granularity] || []).find((entry) => {
    return date >= entry.period_start && date <= entry.period_end;
  }) || null;
}

/**
 * 功能说明：生成按粒度变化的选择面板，日选日期、周选整行、月选月份。
 * 参数 granularity：day、week 或 month。
 * 参数 selectedKey：当前选中的报告周期键。
 * 参数 onSelect：选中报告条目后的回调函数。
 * 参数 compact：是否使用紧凑弹层尺寸。
 * 返回值：完成事件绑定的周期选择面板 DOM 元素。
 */
function createPeriodSelector(granularity, selectedKey, onSelect, compact = false) {
  if (granularity === "day") {
    const selectedEntry = (state.index?.reports?.day || []).find((entry) => entry.period_key === selectedKey);
    const selected = selectedEntry?.period_start || latestEntry("day")?.period_start || state.selectedDay;
    return createDayCalendar(selected, (date) => onSelect(matchingEntry("day", date)), compact);
  }

  const root = document.createElement("div");
  root.className = `period-board${compact ? " period-board--compact" : ""}`;
  const entries = state.index?.reports?.[granularity] || [];
  const activeKey = selectedKey || latestEntry(granularity)?.period_key;
  if (granularity === "week") {
    root.innerHTML = `
      <header class="period-board-heading"><strong>${weekScopeLabel(entries)}</strong><span>选择整周报告</span></header>
      <div class="week-list">
        ${entries.map((entry) => `<button type="button" data-period-key="${entry.period_key}" class="${entry.period_key === activeKey ? "is-selected" : ""}"><span>第 ${isoWeekNumber(entry.period_start)} 周</span><strong>${formatWeekRange(entry.period_start, entry.period_end)}</strong><i class="${isCrossMonth(entry) ? "cross-boundary" : ""}">${isCrossMonth(entry) ? "跨月" : "7 天"}</i></button>`).join("")}
      </div>
    `;
  } else {
    root.innerHTML = `
      <header class="period-board-heading"><strong>2026 年</strong><span>选择月份报告</span></header>
      <div class="month-list">
        ${Array.from({ length: 12 }, (_, index) => {
          const month = index + 1;
          const entry = entries.find((item) => Number(item.period_start.slice(5, 7)) === month);
          return `<button type="button" ${entry ? `data-period-key="${entry.period_key}"` : "disabled"} class="${entry?.period_key === activeKey ? "is-selected" : ""}"><strong>${String(month).padStart(2, "0")}</strong><span>${entry ? "报告可用" : "暂无报告"}</span></button>`;
        }).join("")}
      </div>
    `;
  }
  root.querySelectorAll("[data-period-key]").forEach((button) => {
    const entry = entries.find((item) => item.period_key === button.dataset.periodKey);
    button.addEventListener("click", () => onSelect(entry));
  });
  return root;
}

/**
 * 功能说明：刷新紧凑弹层的粒度按钮、触发器文本和周期选择面板。
 * 返回值：无。
 */
function renderCompactExample() {
  const granularity = state.compactGranularity;
  const entry = (state.index?.reports?.[granularity] || []).find((item) => item.period_key === state.compactKeys[granularity])
    || latestEntry(granularity);
  document.querySelectorAll("[data-compact-granularity]").forEach((button) => {
    const selected = button.dataset.compactGranularity === granularity;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelector("[data-compact-label]").textContent = formatPeriodLabel(granularity, entry);
  const host = document.querySelector("[data-compact-host]");
  host.replaceChildren(createPeriodSelector(granularity, entry?.period_key, (selectedEntry) => {
    selectCompact(granularity, selectedEntry);
  }, true));
}

/**
 * 功能说明：记录紧凑弹层选择结果，并同步当前模拟选择。
 * 参数 granularity：day、week 或 month。
 * 参数 entry：当前选中的报告索引条目。
 * 返回值：无。
 */
function selectCompact(granularity, entry) {
  if (!entry) return;
  state.compactKeys[granularity] = entry.period_key;
  if (granularity === "day") {
    state.selectedDay = entry.period_start;
    renderDayExamples();
  }
  document.querySelector("#shared-selection").textContent = `${granularityLabels[granularity]}分析 · ${formatPeriodLabel(granularity, entry)}`;
  renderCompactExample();
  console.info("Playground 紧凑周期选择完成", { granularity, period: entry.period });
}

function selectAdaptive(granularity, entry) {
  if (!entry) return;
  state.adaptiveKeys[granularity] = entry.period_key;
  document.querySelector("[data-adaptive-result]").textContent = `${granularityLabels[granularity]}分析 · ${formatPeriodLabel(granularity, entry)}`;
  document.querySelector("[data-adaptive-host]").replaceChildren(createPeriodSelector(granularity, entry.period_key, (selectedEntry) => {
    selectAdaptive(granularity, selectedEntry);
  }));
  console.info("Playground 自适应周期选择完成", { granularity, period: entry.period });
}

/**
 * 功能说明：初始化自适应粒度切换与对应周期选择面板。
 * 返回值：无。
 */
function renderAdaptiveExample() {
  const tabs = document.querySelector("[data-adaptive-tabs]");
  tabs.innerHTML = Object.entries(granularityLabels).map(([key, label]) => {
    const count = state.index?.reports?.[key]?.length || 0;
    return `<button type="button" data-adaptive-granularity="${key}" class="${key === state.adaptiveGranularity ? "is-selected" : ""}">${label}<span>${count}</span></button>`;
  }).join("");
  tabs.querySelectorAll("[data-adaptive-granularity]").forEach((button) => {
    button.addEventListener("click", () => {
      state.adaptiveGranularity = button.dataset.adaptiveGranularity;
      renderAdaptiveExample();
      const entry = latestEntry(state.adaptiveGranularity);
      selectAdaptive(state.adaptiveGranularity, entry);
    });
  });
  document.querySelector("[data-adaptive-host]").replaceChildren(createPeriodSelector(
    state.adaptiveGranularity,
    state.adaptiveKeys[state.adaptiveGranularity],
    (selectedEntry) => selectAdaptive(state.adaptiveGranularity, selectedEntry)
  ));
}

function bindDisclosureControls() {
  const compactTrigger = document.querySelector(".date-trigger");
  const compactPopover = document.querySelector(".calendar-popover");
  compactTrigger.addEventListener("click", () => {
    const open = compactPopover.classList.toggle("is-open");
    compactTrigger.setAttribute("aria-expanded", String(open));
  });
  document.querySelectorAll("[data-compact-granularity]").forEach((button) => {
    button.addEventListener("click", () => {
      state.compactGranularity = button.dataset.compactGranularity;
      selectCompact(state.compactGranularity, latestEntry(state.compactGranularity));
    });
  });

  const railTrigger = document.querySelector(".icon-calendar-button");
  const railCalendar = document.querySelector(".rail-calendar");
  railTrigger.addEventListener("click", () => {
    railCalendar.hidden = !railCalendar.hidden;
    railTrigger.setAttribute("aria-expanded", String(!railCalendar.hidden));
  });
}

/**
 * 功能说明：读取真实报告索引并启动四种周期选择器示例。
 * 返回值：Promise；初始化完成后页面可交互。
 */
async function initializePlayground() {
  console.info("开始初始化分析周期选择器 Playground");
  try {
    state.index = await loadReportIndex();
    state.selectedDay = latestEntry("day")?.period_start || state.selectedDay;
    for (const granularity of Object.keys(granularityLabels)) {
      state.compactKeys[granularity] = latestEntry(granularity)?.period_key || "";
      state.adaptiveKeys[granularity] = latestEntry(granularity)?.period_key || "";
    }
    updateSharedDay(state.selectedDay);
    renderCompactExample();
    renderAdaptiveExample();
    selectAdaptive("day", latestEntry("day"));
    bindDisclosureControls();
    console.info("分析周期选择器 Playground 初始化完成");
  } catch (error) {
    console.error("分析周期选择器 Playground 初始化失败", error);
    document.querySelector("#shared-selection").textContent = "报告索引读取失败";
  }
}

initializePlayground();
