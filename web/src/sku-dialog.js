import { loadReportSkus } from "./data-client.js";

let requestId = 0;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function displayValue(value) {
  const text = String(value ?? "").trim();
  return text || "-";
}

/**
 * 功能说明：把报告对应的本品 SKU 五字段列表渲染到弹窗。
 * 参数 dialog：承载 SKU 构成的原生 dialog 元素。
 * 参数 data：Backend 返回的报告 SKU 构成对象。
 * 返回值：无；直接更新弹窗标题、摘要和表格内容。
 */
export function renderSkuDialog(dialog, data) {
  dialog.querySelector("#sku-dialog-title").textContent = `本品 SKU 构成 · ${data.sku_count || 0} 个`;
  dialog.querySelector("#sku-dialog-meta").textContent = [
    `SPU ${data.spu_id || "-"}`,
    data.start_date === data.end_date
      ? data.start_date
      : `${data.start_date || "-"} 至 ${data.end_date || "-"}`
  ].join(" · ");
  const items = Array.isArray(data.items) ? data.items : [];
  dialog.querySelector("#sku-dialog-body").innerHTML = items.length ? `
    <div class="sku-table-wrap">
      <table class="sku-table">
        <thead>
          <tr>
            <th>SPU ID</th>
            <th>SKU ID</th>
            <th>69 码</th>
            <th>商品名</th>
            <th>规格</th>
          </tr>
        </thead>
        <tbody>
          ${items.map((item) => `
            <tr>
              <td>${escapeHtml(displayValue(item.spu_id))}</td>
              <td>${escapeHtml(displayValue(item.sku_id))}</td>
              <td>${escapeHtml(displayValue(item.barcode_69))}</td>
              <td>${escapeHtml(displayValue(item.product_name))}</td>
              <td>${escapeHtml(displayValue(item.specification))}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  ` : '<p class="sku-dialog-state">当前报告没有可展示的 SKU 构成。</p>';
}

/**
 * 功能说明：初始化 SKU 构成弹窗，并在点击入口时按当前报告读取数据。
 * 参数 trigger：打开弹窗的按钮。
 * 参数 dialog：展示 SKU 列表的原生 dialog 元素。
 * 参数 getEntry：返回当前报告索引条目的函数。
 * 返回值：无；完成一次性事件绑定。
 */
export function bindSkuDialog(trigger, dialog, getEntry) {
  trigger.addEventListener("click", async () => {
    const entry = getEntry();
    if (!entry) return;
    const currentRequestId = requestId + 1;
    requestId = currentRequestId;
    dialog.querySelector("#sku-dialog-title").textContent = "本品 SKU 构成";
    dialog.querySelector("#sku-dialog-meta").textContent = `正在读取报告 ${entry.start_date || ""} 的 SKU 快照`;
    dialog.querySelector("#sku-dialog-body").innerHTML = '<p class="sku-dialog-state">正在加载 SKU 构成…</p>';
    dialog.showModal();
    try {
      const data = await loadReportSkus(entry);
      if (requestId === currentRequestId && dialog.open) {
        renderSkuDialog(dialog, data);
      }
    } catch (error) {
      console.error("SKU 构成加载失败", error);
      if (requestId === currentRequestId && dialog.open) {
        dialog.querySelector("#sku-dialog-body").innerHTML = '<p class="sku-dialog-state error">SKU 构成加载失败，请稍后重试。</p>';
      }
    }
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
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !dialog.open) return;
    event.preventDefault();
    dialog.close();
  });
  dialog.addEventListener("close", () => {
    requestId += 1;
    trigger.focus();
  });
}

/**
 * 功能说明：在切换报告时关闭仍然打开的 SKU 构成弹窗。
 * 参数 dialog：SKU 构成的原生 dialog 元素。
 * 返回值：无。
 */
export function closeSkuDialog(dialog) {
  if (dialog.open) dialog.close();
}
