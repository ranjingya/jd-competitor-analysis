const weekdayLabels = ["一", "二", "三", "四", "五", "六", "日"];
const calendarWeeks = [
  ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-06", "2026-06-07"],
  ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13", "2026-06-14"],
  ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19", "2026-06-20", "2026-06-21"],
  ["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28"],
  ["2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"]
];

const styleOptions = [
  {
    id: "classic",
    badge: "最接近旧周样式",
    name: "经典描边",
    description: "保留竖向分隔和浅色跨月格，选中范围使用青色描边。"
  },
  {
    id: "band",
    badge: "整体感更强",
    name: "连续色带",
    description: "表格结构不变，选中范围形成连续浅色带，边界更轻。"
  },
  {
    id: "cells",
    badge: "边界最清楚",
    name: "独立分格",
    description: "每个日期都有细描边，适合强调日期是可操作单元。"
  },
  {
    id: "underline",
    badge: "最克制",
    name: "底线强调",
    description: "保留周表结构，只用底色和底线标记当前日或当前周。"
  }
];

function dateParts(value) {
  const [year, month, day] = value.split("-").map(Number);
  return { year, month, day };
}

function utcDate(value) {
  const { year, month, day } = dateParts(value);
  return new Date(Date.UTC(year, month - 1, day));
}

function isoWeekNumber(value) {
  const date = utcDate(value);
  const weekday = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - weekday);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  return Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
}

function dateLabel(value) {
  const { month, day } = dateParts(value);
  return month === 6 ? String(day) : `${month}/${day}`;
}

function rangeLabel(week) {
  const start = dateParts(week[0]);
  const end = dateParts(week.at(-1));
  return `${start.year}年${start.month}月${start.day}日—${end.month}月${end.day}日`;
}

function weekdayHeader() {
  return `<div class="weekday-row">${weekdayLabels.map((label) => `<span>${label}</span>`).join("")}</div>`;
}

function dayGrid(selectedDay) {
  return `
    <div class="date-grid day-grid" role="grid" aria-label="选择单日">
      ${calendarWeeks.flat().map((date) => {
        const outside = dateParts(date).month !== 6;
        const selected = date === selectedDay;
        return `<button type="button" class="date-cell${outside ? " is-outside" : ""}${selected ? " is-selected" : ""}" data-day="${date}" aria-pressed="${selected}">${dateLabel(date)}</button>`;
      }).join("")}
    </div>
  `;
}

function weekGrid(selectedWeek) {
  return `
    <div class="date-grid week-grid" role="grid" aria-label="选择自然周">
      ${calendarWeeks.map((week, index) => `
        <button type="button" class="week-row${index === selectedWeek ? " is-selected" : ""}" data-week="${index}" aria-pressed="${index === selectedWeek}">
          ${week.map((date) => `<span class="date-cell${dateParts(date).month !== 6 ? " is-outside" : ""}">${dateLabel(date)}</span>`).join("")}
        </button>
      `).join("")}
    </div>
  `;
}

/**
 * 功能说明：按当前模式渲染单个日历方案，并保持日、周日期坐标一致。
 * 参数 card：承载方案预览的卡片元素。
 * 返回值：无；直接更新卡片内的日历与周摘要。
 */
function renderCalendar(card) {
  const mode = card.dataset.mode || "week";
  const selectedDay = card.dataset.selectedDay || "2026-06-07";
  const selectedWeek = Number(card.dataset.selectedWeek || 4);
  const selectedWeekDates = calendarWeeks[selectedWeek];
  const target = card.querySelector("[data-calendar-body]");
  target.innerHTML = `
    <div class="calendar-heading">
      <button type="button" aria-label="上一个月">‹</button>
      <div><strong>2026 年 6 月</strong><span>${mode === "day" ? "选择单日报告" : "选择完整自然周"}</span></div>
      <button type="button" aria-label="下一个月">›</button>
    </div>
    ${weekdayHeader()}
    ${mode === "day" ? dayGrid(selectedDay) : weekGrid(selectedWeek)}
    <footer class="week-summary${mode === "day" ? " is-placeholder" : ""}">
      <span>第 ${isoWeekNumber(selectedWeekDates[0])} 周 · 跨月</span>
      <strong>${rangeLabel(selectedWeekDates)}</strong>
    </footer>
  `;
  card.querySelectorAll("[data-day]").forEach((button) => {
    button.addEventListener("click", () => {
      card.dataset.selectedDay = button.dataset.day;
      console.info("日历样式预览选择日期", { style: card.dataset.style, date: button.dataset.day });
      renderCalendar(card);
    });
  });
  card.querySelectorAll("[data-week]").forEach((button) => {
    button.addEventListener("click", () => {
      card.dataset.selectedWeek = button.dataset.week;
      console.info("日历样式预览选择自然周", { style: card.dataset.style, weekIndex: Number(button.dataset.week) });
      renderCalendar(card);
    });
  });
}

/**
 * 功能说明：创建一套可独立切换日、周模式的日历样式预览卡片。
 * 参数 option：样式方案的标识、名称、标签和说明。
 * 返回值：完成交互绑定的预览卡片元素。
 */
function createPreviewCard(option) {
  const card = document.createElement("article");
  card.className = `preview-card style-${option.id}`;
  card.dataset.style = option.id;
  card.dataset.mode = "week";
  card.dataset.selectedDay = "2026-06-07";
  card.dataset.selectedWeek = "4";
  card.innerHTML = `
    <header class="preview-card-header">
      <div>
        <span class="option-badge">${option.badge}</span>
        <h2>${option.name}</h2>
        <p>${option.description}</p>
      </div>
      <div class="mode-switch" aria-label="日历模式">
        <button type="button" data-mode="day">日</button>
        <button type="button" data-mode="week" class="is-active">周</button>
      </div>
    </header>
    <section class="calendar-frame" data-calendar-body></section>
  `;
  card.querySelectorAll("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      card.dataset.mode = button.dataset.mode;
      card.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("is-active", item === button));
      console.info("日历样式预览切换模式", { style: option.id, mode: button.dataset.mode });
      renderCalendar(card);
    });
  });
  renderCalendar(card);
  return card;
}

/**
 * 功能说明：初始化日历样式对比页并渲染全部候选方案。
 * 返回值：无；直接填充页面方案网格。
 */
function initializePlayground() {
  console.info("开始渲染日历样式对比页", { optionCount: styleOptions.length });
  const grid = document.querySelector("#preview-grid");
  grid.replaceChildren(...styleOptions.map(createPreviewCard));
  console.info("日历样式对比页渲染完成", { optionCount: styleOptions.length });
}

initializePlayground();
