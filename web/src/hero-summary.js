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
 * 功能说明：判断详情值是否包含至少一个可展示的文本要点。
 * 参数 value：详情数组或详情字符串。
 * 返回值：存在非空文本时返回 true，否则返回 false。
 */
export function hasDetailPoints(value) {
  if (Array.isArray(value)) {
    return value.some((item) => typeof item === "string" && item.trim());
  }
  return typeof value === "string" && Boolean(value.trim());
}

/**
 * 功能说明：把一段详情文本按自然语义边界拆成独立要点。
 * 参数 value：待拆分的详情文本。
 * 返回值：过滤空值并清理列表符号后的要点数组。
 */
function splitDetailText(value) {
  const text = String(value || "").trim();
  if (!text) return [];
  return (text.match(/[^\n。！？；]+[。！？；]?/gu) || [text])
    .map((item) => item.replace(/^\s*[-•·]\s*/u, "").trim())
    .filter(Boolean);
}

/**
 * 功能说明：把详情统一转换为逐条展示的文本数组。
 * 参数 value：详情数组或详情字符串。
 * 返回值：过滤空值后的详情要点；无内容时返回占位项。
 */
export function detailPoints(value) {
  if (Array.isArray(value)) {
    const points = value.flatMap((item) => splitDetailText(item));
    return points.length ? points : ["-"];
  }
  const points = splitDetailText(value);
  return points.length ? points : ["-"];
}

/**
 * 功能说明：把结论详情按无序列表写入弹窗。
 * 参数 container：承载详情条目的列表元素。
 * 参数 value：详情数组或详情字符串。
 * 返回值：无；直接替换列表中的详情条目。
 */
function renderDetailPoints(container, value) {
  container.replaceChildren(...detailPoints(value).map((point) => {
    const item = document.createElement("li");
    item.textContent = point;
    return item;
  }));
}

/**
 * 功能说明：读取摘要按钮中经过 JSON 编码的详情数据。
 * 参数 value：按钮 dataset 中保存的字符串。
 * 返回值：解析后的详情数组或兼容的原始字符串。
 */
function parseDetail(value) {
  try {
    return JSON.parse(value || "\"-\"");
  } catch {
    return value || "-";
  }
}

/**
 * 功能说明：绑定优点与弱点摘要的详情弹窗。
 * 参数 dialog：用于展示完整结论的原生 dialog 元素。
 * 参数 trigger：打开优缺点详情的摘要面板按钮。
 * 返回值：无；完成点击、遮罩关闭和焦点恢复事件绑定。
 */
export function bindHeroSummaryDialog(dialog, trigger) {
  trigger.addEventListener("click", () => {
    renderDetailPoints(
      dialog.querySelector("#summary-dialog-advantage"),
      parseDetail(trigger.dataset.advantageDetail)
    );
    renderDetailPoints(
      dialog.querySelector("#summary-dialog-weakness"),
      parseDetail(trigger.dataset.weaknessDetail)
    );
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
