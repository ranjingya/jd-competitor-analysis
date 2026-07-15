import { loadReportIndex } from "./data-client.js";

const granularityLabels = { day: "日", week: "周", month: "月" };
const weekdayLabels = ["一", "二", "三", "四", "五", "六", "日"];
const motionPresets = {
  spring: { title: "柔和回弹", description: "轻微越过终点再回落，反馈最明确。" },
  snap: { title: "磁吸展开", description: "从触发器边缘快速展开，停靠感更强。" },
  fold: { title: "翻页落位", description: "沿顶部轴线翻开，强化日历的纸张感。" },
  glide: { title: "侧滑减速", description: "从右侧快速滑入后减速，方向感最明显。" }
};

const state = {
  index: null,
  activeGranularity: "day",
  selectedKeys: {},
  motion: "spring"
};

function dateParts(value) {
  const [year, month, day] = String(value).split("-").map(Number);
  return { year, month, day };
}

function isoDate(date) {
  return [
    date.getUTCFullYear(),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0")
  ].join("-");
}

function utcDate(value) {
  const { year, month, day } = dateParts(value);
  return new Date(Date.UTC(year, month - 1, day));
}

function reportsFor(granularity) {
  return state.index?.reports?.[granularity] || [];
}

function latestEntry(granularity) {
  return reportsFor(granularity).at(-1) || null;
}

function selectedEntry(granularity = state.activeGranularity) {
  return reportsFor(granularity).find((entry) => entry.period_key === state.selectedKeys[granularity])
    || latestEntry(granularity);
}

function formatDayLabel(value, includeYear = true) {
  const { year, month, day } = dateParts(value);
  return `${includeYear ? `${year}年` : ""}${month}月${day}日`;
}

/**
 * 功能说明：把周起止日期格式化为易读范围，完整保留跨月和跨年边界。
 * 参数 start：周开始日期，格式为 YYYY-MM-DD。
 * 参数 end：周结束日期，格式为 YYYY-MM-DD。
 * 返回值：适合界面展示的中文日期范围。
 */
function formatWeekRange(start, end) {
  const from = dateParts(start);
  const to = dateParts(end);
  if (from.year !== to.year) {
    return `${formatDayLabel(start)}—${formatDayLabel(end)}`;
  }
  if (from.month !== to.month) {
    return `${formatDayLabel(start)}—${formatDayLabel(end, false)}`;
  }
  return `${formatDayLabel(start)}—${to.day}日`;
}

function formatPeriodLabel(granularity, entry) {
  if (!entry) return "暂无报告";
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

/**
 * 功能说明：生成覆盖指定月份的完整自然周日期矩阵，包含月初和月末的相邻月份日期。
 * 参数 year：四位年份。
 * 参数 month：从 1 开始的月份。
 * 返回值：按自然周排列的 ISO 日期二维数组。
 */
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

function periodContext() {
  const entry = selectedEntry() || latestEntry("day");
  const { year, month } = dateParts(entry?.period_start || new Date().toISOString().slice(0, 10));
  return { year, month, entry };
}

function weekdayHeader() {
  return `<div class="weekday-row">${weekdayLabels.map((label) => `<span>${label}</span>`).join("")}</div>`;
}

function monthHeader(year, month, note) {
  return `
    <header class="calendar-header">
      <button type="button" aria-label="上个月" disabled>‹</button>
      <div><strong>${year} 年 ${month} 月</strong><span>${note}</span></div>
      <button type="button" aria-label="下个月" disabled>›</button>
    </header>
  `;
}

/**
 * 功能说明：创建日维度日期面板，只有存在日报的日期可点击。
 * 参数 year：当前展示年份。
 * 参数 month：当前展示月份。
 * 返回值：日维度面板 DOM 元素。
 */
function createDayPanel(year, month) {
  const root = document.createElement("div");
  root.className = "calendar-panel";
  const selected = selectedEntry("day");
  const available = new Map(reportsFor("day").map((entry) => [entry.period_start, entry]));
  const weeks = calendarWeeks(year, month);
  root.innerHTML = `
    ${monthHeader(year, month, "选择单日报告")}
    ${weekdayHeader()}
    <div class="day-grid">
      ${weeks.flat().map((date) => {
        const parts = dateParts(date);
        const entry = available.get(date);
        const outside = parts.month !== month;
        return `<button type="button" data-day="${date}" class="day-cell${outside ? " is-outside" : ""}${entry ? " has-report" : ""}${entry?.period_key === selected?.period_key ? " is-selected" : ""}" ${entry ? "" : "disabled"} aria-pressed="${entry?.period_key === selected?.period_key}"><span>${outside ? `${parts.month}/${parts.day}` : parts.day}</span>${entry ? "<i></i>" : ""}</button>`;
      }).join("")}
    </div>
  `;
  root.querySelectorAll("[data-day]:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => selectPeriod("day", available.get(button.dataset.day)));
  });
  return root;
}

/**
 * 功能说明：创建周维度日历面板，每份周报告使用包含七天日期的整行按钮表示。
 * 参数 year：当前展示年份。
 * 参数 month：当前展示月份。
 * 返回值：周维度面板 DOM 元素。
 */
function createWeekPanel(year, month) {
  const root = document.createElement("div");
  root.className = "calendar-panel week-panel";
  const selected = selectedEntry("week");
  const monthStart = `${year}-${String(month).padStart(2, "0")}-01`;
  const monthEnd = isoDate(new Date(Date.UTC(year, month, 0)));
  const entries = reportsFor("week").filter((entry) => entry.period_end >= monthStart && entry.period_start <= monthEnd);
  root.innerHTML = `
    ${monthHeader(year, month, "选择完整自然周")}
    ${weekdayHeader()}
    <div class="week-grid">
      ${entries.map((entry) => {
        const dates = datesInRange(entry.period_start, entry.period_end);
        const crossMonth = isCrossMonth(entry);
        return `
          <button type="button" class="week-row${entry.period_key === selected?.period_key ? " is-selected" : ""}" data-week-key="${entry.period_key}" aria-pressed="${entry.period_key === selected?.period_key}" aria-label="第 ${isoWeekNumber(entry.period_start)} 周，${formatWeekRange(entry.period_start, entry.period_end)}">
            ${dates.map((date) => {
              const parts = dateParts(date);
              const outside = parts.month !== month;
              return `<span class="week-day${outside ? " is-outside" : ""}"><b>${outside ? `${parts.month}/${parts.day}` : parts.day}</b><i>${outside && parts.day === 1 ? `${parts.month}月` : ""}</i></span>`;
            }).join("")}
          </button>
        `;
      }).join("")}
    </div>
    <footer class="week-summary">
      <span>第 ${isoWeekNumber(selected?.period_start)} 周${isCrossMonth(selected) ? " · 跨月" : ""}</span>
      <strong>${formatWeekRange(selected?.period_start, selected?.period_end)}</strong>
    </footer>
  `;
  root.querySelectorAll("[data-week-key]").forEach((button) => {
    const entry = entries.find((item) => item.period_key === button.dataset.weekKey);
    button.addEventListener("click", () => selectPeriod("week", entry));
  });
  return root;
}

/**
 * 功能说明：创建月维度年份面板，只有存在月报的月份可点击。
 * 参数 year：当前展示年份。
 * 返回值：月维度面板 DOM 元素。
 */
function createMonthPanel(year) {
  const root = document.createElement("div");
  root.className = "calendar-panel month-panel";
  const selected = selectedEntry("month");
  const entries = reportsFor("month").filter((entry) => Number(entry.period_start.slice(0, 4)) === year);
  root.innerHTML = `
    <header class="calendar-header year-header">
      <button type="button" aria-label="上一年" disabled>‹</button>
      <div><strong>${year} 年</strong><span>选择整月报告</span></div>
      <button type="button" aria-label="下一年" disabled>›</button>
    </header>
    <div class="month-grid">
      ${Array.from({ length: 12 }, (_, index) => {
        const month = index + 1;
        const entry = entries.find((item) => Number(item.period_start.slice(5, 7)) === month);
        return `<button type="button" ${entry ? `data-month-key="${entry.period_key}"` : "disabled"} class="month-cell${entry?.period_key === selected?.period_key ? " is-selected" : ""}" aria-pressed="${entry?.period_key === selected?.period_key}"><strong>${String(month).padStart(2, "0")}</strong><span>${entry ? "报告可用" : "暂无报告"}</span></button>`;
      }).join("")}
    </div>
  `;
  root.querySelectorAll("[data-month-key]").forEach((button) => {
    const entry = entries.find((item) => item.period_key === button.dataset.monthKey);
    button.addEventListener("click", () => selectPeriod("month", entry));
  });
  return root;
}

function createSelectorPanel() {
  const { year, month } = periodContext();
  if (state.activeGranularity === "week") return createWeekPanel(year, month);
  if (state.activeGranularity === "month") return createMonthPanel(year);
  return createDayPanel(year, month);
}

/**
 * 功能说明：渲染紧凑弹层的左侧粒度栏和右侧时间选择面板。
 * 返回值：无。
 */
function renderPopover() {
  const popover = document.querySelector("#period-popover");
  popover.innerHTML = `
    <nav class="granularity-rail" aria-label="分析粒度">
      ${Object.entries(granularityLabels).map(([key, label]) => `
        <button type="button" data-granularity="${key}" class="${key === state.activeGranularity ? "is-selected" : ""}" aria-pressed="${key === state.activeGranularity}">
          <strong>${label}</strong><span>${reportsFor(key).length}</span>
        </button>
      `).join("")}
    </nav>
    <section class="selector-content" data-selector-content></section>
  `;
  popover.querySelector("[data-selector-content]").replaceChildren(createSelectorPanel());
  popover.querySelectorAll("[data-granularity]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeGranularity = button.dataset.granularity;
      const entry = selectedEntry(state.activeGranularity);
      updateSelectionLabels(state.activeGranularity, entry);
      renderPopover();
      console.info("Playground 分析粒度切换完成", { granularity: state.activeGranularity });
    });
  });
}

function updateSelectionLabels(granularity, entry) {
  const label = formatPeriodLabel(granularity, entry);
  document.querySelector("#trigger-label").textContent = label;
  document.querySelector("#current-selection").textContent = `${granularityLabels[granularity]}分析 · ${label}`;
}

/**
 * 功能说明：记录选中的报告周期，并刷新弹层和界面选择结果。
 * 参数 granularity：day、week 或 month。
 * 参数 entry：选中的报告索引条目。
 * 返回值：无。
 */
function selectPeriod(granularity, entry) {
  if (!entry) return;
  state.selectedKeys[granularity] = entry.period_key;
  updateSelectionLabels(granularity, entry);
  renderPopover();
  console.info("Playground 报告周期选择完成", { granularity, period: entry.period });
}

function bindPopoverTrigger() {
  const trigger = document.querySelector("#period-trigger");
  const popover = document.querySelector("#period-popover");
  trigger.addEventListener("click", () => {
    const open = popover.classList.toggle("is-open");
    trigger.setAttribute("aria-expanded", String(open));
  });
}

function updateMotionControls() {
  const preset = motionPresets[state.motion];
  document.querySelector("#motion-title").textContent = preset.title;
  document.querySelector("#motion-description").textContent = preset.description;
  document.querySelectorAll("#motion-options [data-motion]").forEach((button) => {
    const selected = button.dataset.motion === state.motion;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

/**
 * 功能说明：应用指定入场动效并立即重播日历弹层。
 * 参数 motion：spring、snap、fold 或 glide 动效标识。
 * 返回值：无。
 */
function replayMotion(motion) {
  if (!motionPresets[motion]) return;
  state.motion = motion;
  const trigger = document.querySelector("#period-trigger");
  const popover = document.querySelector("#period-popover");
  popover.dataset.motion = motion;
  popover.classList.remove("is-open");
  trigger.setAttribute("aria-expanded", "false");
  void popover.offsetWidth;
  requestAnimationFrame(() => {
    popover.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  });
  updateMotionControls();
  console.info("Playground 入场动效重播", { motion });
}

function bindMotionControls() {
  document.querySelectorAll("#motion-options [data-motion]").forEach((button) => {
    button.addEventListener("click", () => replayMotion(button.dataset.motion));
  });
}

/**
 * 功能说明：读取真实报告索引并初始化单一的日周月日历 Playground。
 * 返回值：Promise；初始化完成后页面可交互。
 */
async function initializePlayground() {
  console.info("开始初始化分析周期日历 Playground");
  try {
    state.index = await loadReportIndex();
    for (const granularity of Object.keys(granularityLabels)) {
      state.selectedKeys[granularity] = latestEntry(granularity)?.period_key || "";
    }
    const entry = selectedEntry();
    updateSelectionLabels(state.activeGranularity, entry);
    renderPopover();
    bindPopoverTrigger();
    bindMotionControls();
    updateMotionControls();
    console.info("分析周期日历 Playground 初始化完成");
  } catch (error) {
    console.error("分析周期日历 Playground 初始化失败", error);
    document.querySelector("#current-selection").textContent = "报告索引读取失败";
    document.querySelector("#trigger-label").textContent = "暂无可用报告";
  }
}

initializePlayground();
