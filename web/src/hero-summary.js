/**
 * 功能说明：根据核心指标状态生成首屏可完整阅读的短摘要。
 * 参数 metrics：报告中的四张核心指标卡。
 * 参数 kind：摘要类型，advantage 表示优点，warning 表示弱点。
 * 返回值：由匹配指标名称组成的简短结论。
 */
export function compactHeroSummary(metrics, kind) {
  const labels = [...new Set((Array.isArray(metrics) ? metrics : [])
    .filter((item) => item?.status === kind && String(item?.label || "").trim())
    .map((item) => String(item.label).trim()))];
  if (!labels.length) {
    return kind === "warning" ? "暂无明显短板" : "暂无明显优势";
  }
  const visibleLabels = labels.slice(0, 3).join("、");
  const overflowMark = labels.length > 3 ? "等" : "";
  return `${visibleLabels}${overflowMark}${kind === "warning" ? "落后" : "领先"}`;
}

/**
 * 功能说明：绑定优点与弱点摘要的详情弹窗。
 * 参数 dialog：用于展示完整结论的原生 dialog 元素。
 * 参数 trigger：打开优缺点详情的摘要面板按钮。
 * 返回值：无；完成点击、遮罩关闭和焦点恢复事件绑定。
 */
export function bindHeroSummaryDialog(dialog, trigger) {
  trigger.addEventListener("click", () => {
    dialog.querySelector("#summary-dialog-advantage").textContent = trigger.dataset.advantageDetail || "-";
    dialog.querySelector("#summary-dialog-weakness").textContent = trigger.dataset.weaknessDetail || "-";
    dialog.showModal();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    const inside = event.clientX >= bounds.left
      && event.clientX <= bounds.right
      && event.clientY >= bounds.top
      && event.clientY <= bounds.bottom;
    if (!inside) dialog.close();
  });
  dialog.addEventListener("close", () => {
    trigger.focus();
  });
}
