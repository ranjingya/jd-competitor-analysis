function formatDate(value) {
  if (!value) return "未知日期";
  const [, month, day] = String(value).split("-").map(Number);
  return month && day ? `${month}月${day}日` : String(value);
}

function uniqueDates(values) {
  return [...new Set((Array.isArray(values) ? values : []).filter(Boolean))].sort();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/**
 * 功能说明：根据报告覆盖率与处理状态生成统一的前端异常展示模型。
 * 参数 report：后端返回的完整报告对象。
 * 返回值：无需提示时返回 null；否则返回状态条和明细弹窗所需数据。
 */
export function reportStatusModel(report) {
  const meta = report?.meta || {};
  const missingDays = uniqueDates(meta.missing_days);
  const periodDays = Number(meta.period_days || 0);
  const availableDays = Number.isFinite(Number(meta.available_days))
    ? Number(meta.available_days)
    : Math.max(0, periodDays - missingDays.length);
  const reportStatus = String(report?.report_status || "ready");
  const aiFailed = reportStatus === "ai_failed";
  const aiPending = reportStatus === "pending_ai";
  const details = missingDays.map((date) => ({
    date,
    symbol: "—",
    label: "无数据",
    tone: "missing",
    reason: "这一天没有可用于周期聚合的日报。"
  }));

  if (aiFailed) {
    details.push({
      date: meta.period_end || meta.period_start,
      symbol: "!",
      label: "AI 失败",
      tone: "danger",
      reason: "确定性计算已完成，AI 优劣势与建议暂不可用。"
    });
  } else if (aiPending) {
    details.push({
      date: meta.period_end || meta.period_start,
      symbol: "…",
      label: "AI 生成中",
      tone: "pending",
      reason: "确定性计算已完成，AI 优劣势与建议正在生成。"
    });
  }

  if (missingDays.length) {
    const coverage = periodDays > 0 ? `${availableDays}/${periodDays} 天可用` : "存在缺失日期";
    const missingText = missingDays.map(formatDate).join("、");
    const aiText = aiFailed ? "；AI 分析失败" : aiPending ? "；AI 分析生成中" : "";
    return {
      tone: aiFailed ? "danger" : "warning",
      symbol: "▲",
      title: `数据不完整 · ${coverage}`,
      detail: `${missingText}无数据${aiText}`,
      dialogTitle: "报告状态明细",
      dialogSubtitle: `${meta.period || `${meta.period_start || ""} 至 ${meta.period_end || ""}`} · ${coverage}`,
      details
    };
  }

  if (aiFailed || aiPending) {
    return {
      tone: aiFailed ? "danger" : "pending",
      symbol: aiFailed ? "!" : "…",
      title: aiFailed ? "AI 分析失败 · 基础报告可用" : "AI 分析生成中 · 基础报告可用",
      detail: aiFailed
        ? "核心指标、趋势和差距来源仍可查看"
        : "核心指标、趋势和差距来源已完成",
      dialogTitle: "报告状态明细",
      dialogSubtitle: meta.period || meta.period_start || "当前报告",
      details
    };
  }

  return null;
}

/**
 * 功能说明：渲染当前报告的异常状态条，并准备弹窗明细数据。
 * 参数 report：后端返回的完整报告对象。
 * 返回值：无；直接更新页面中的状态条。
 */
export function renderReportStatus(report) {
  const trigger = document.querySelector("#report-status-trigger");
  const model = reportStatusModel(report);
  if (!trigger) return;
  if (!model) {
    trigger.hidden = true;
    trigger.dataset.statusModel = "";
    return;
  }
  trigger.hidden = false;
  trigger.dataset.tone = model.tone;
  trigger.dataset.statusModel = JSON.stringify(model);
  trigger.querySelector("[data-status-symbol]").textContent = model.symbol;
  trigger.querySelector("[data-status-title]").textContent = model.title;
  trigger.querySelector("[data-status-detail]").textContent = model.detail;
}

/**
 * 功能说明：绑定状态条与原生对话框的打开、关闭和明细渲染事件。
 * 参数 trigger：报告异常状态条按钮。
 * 参数 dialog：报告状态明细对话框。
 * 返回值：无；完成一次性事件绑定。
 */
export function bindReportStatusDialog(trigger, dialog) {
  if (!trigger || !dialog) return;
  const closeButton = dialog.querySelector("[data-report-status-close]");
  trigger.addEventListener("click", () => {
    const model = JSON.parse(trigger.dataset.statusModel || "null");
    if (!model) return;
    dialog.querySelector("#report-status-dialog-title").textContent = model.dialogTitle;
    dialog.querySelector("#report-status-dialog-subtitle").textContent = model.dialogSubtitle;
    dialog.querySelector("#report-status-dialog-body").innerHTML = model.details.map((item) => `
      <div class="report-status-row">
        <time datetime="${escapeHtml(item.date || "")}">${escapeHtml(formatDate(item.date))}</time>
        <span class="report-status-pill tone-${escapeHtml(item.tone)}"><span aria-hidden="true">${escapeHtml(item.symbol)}</span>${escapeHtml(item.label)}</span>
        <span>${escapeHtml(item.reason)}</span>
      </div>
    `).join("");
    dialog.showModal();
  });
  closeButton?.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}
