import { createApp, h, nextTick, onBeforeUnmount, ref } from "vue";
import VxeUITable, { VxeColumn, VxeTable } from "vxe-table";
import "vxe-pc-ui/lib/style.css";
import "vxe-table/lib/style.css";
import "./analysis-vxe-table.css";

const GAP_FIELD_PATTERN = /(gap|差距|visitor_gap|gmv_gap|order_gap|gap_rate)/;
const BAD_TEXT_PATTERN = /落后|竞品独有|补词机会|成交落后|访客落后|短板/;
const GOOD_TEXT_PATTERN = /领先|本品独有|本品优势|优势|保持优势/;

let mountedTable = null;

/**
 * 功能说明：统一格式化 VXE 表格中的数值，保留两位小数且不使用千位分隔符。
 * 参数 value：待展示的原始值。
 * 参数 unit：列定义中的展示单位。
 * 返回值：可直接展示的文本。
 */
function formatTableValue(value, unit = "") {
  if (value == null || value === "" || value === "-") {
    return "-";
  }
  return typeof value === "number" ? `${value.toFixed(2)}${unit}` : `${value}${unit}`;
}

/**
 * 功能说明：根据判断文本或差距数值返回优势、劣势或中性样式。
 * 参数 value：当前单元格的原始值。
 * 参数 column：当前列定义。
 * 返回值：单元格内容使用的 CSS 类名。
 */
function valueTone(value, column) {
  const text = String(value ?? "");
  const key = String(column.key || "");
  if (BAD_TEXT_PATTERN.test(text)) {
    return "analysis-value-bad";
  }
  if (GOOD_TEXT_PATTERN.test(text)) {
    return "analysis-value-good";
  }
  if (typeof value === "number" && GAP_FIELD_PATTERN.test(key)) {
    return value > 0
      ? "analysis-value-good"
      : value < 0
        ? "analysis-value-bad"
        : "analysis-value-neutral";
  }
  return value == null || text === "-" ? "analysis-value-neutral" : "";
}

/**
 * 功能说明：把渠道路径数据转换成 VXE-Table transform 树所需的扁平父子关系。
 * 参数 rows：流量来源的原始渠道行。
 * 返回值：带稳定 id、parent_id 和末级名称的扁平渠道数组。
 */
function prepareTrafficRows(rows) {
  return rows.map((row, index) => {
    const levels = [row.level_1, row.level_2, row.level_3]
      .filter((value) => value != null && value !== "" && value !== "-");
    const pathKey = levels.join("\u001f") || `${row.path || "row"}-${index}`;
    const parentKey = levels.length > 1 ? levels.slice(0, -1).join("\u001f") : null;
    return {
      ...row,
      id: `traffic:${pathKey}`,
      parent_id: parentKey ? `traffic:${parentKey}` : null,
      path: levels.at(-1) || row.path || "-"
    };
  });
}

/**
 * 功能说明：为普通维度行补充 VXE-Table 所需的稳定行标识。
 * 参数 rows：当前维度的原始数据行。
 * 参数 tableId：当前维度 ID。
 * 返回值：带稳定 id 的新数据数组。
 */
function prepareFlatRows(rows, tableId) {
  return rows.map((row, index) => ({ ...row, id: `${tableId}:${index}` }));
}

/**
 * 功能说明：根据列名和维度分配紧凑列宽，保证冻结区不过度占用横向空间。
 * 参数 column：当前列定义。
 * 参数 columnIndex：当前列序号。
 * 参数 tableId：当前维度 ID。
 * 返回值：以像素为单位的列宽。
 */
function columnWidth(column, columnIndex, tableId) {
  if (columnIndex === 0) {
    return tableId === "traffic" ? 196 : tableId === "keywords" ? 168 : 142;
  }
  if (columnIndex === 1) {
    return 108;
  }
  const labelLength = String(column.label || "").length;
  return Math.min(Math.max(112, labelLength * 15 + 32), 172);
}

/**
 * 功能说明：生成表格放大窗口的切换图标。
 * 参数 expanded：当前表格是否处于放大窗口状态。
 * 返回值：Vue SVG 虚拟节点。
 */
function expandIcon(expanded) {
  const path = expanded
    ? "M9 3v6H3M15 3v6h6M9 21v-6H3M15 21v-6h6"
    : "M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5";
  return h("svg", {
    viewBox: "0 0 24 24",
    width: "17",
    height: "17",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "1.8",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "aria-hidden": "true"
  }, [h("path", { d: path })]);
}

/**
 * 功能说明：把当前维度挂载为 Vue 3 与 VXE-Table 表格，并提供居中放大窗口。
 * 参数 target：表格挂载容器。
 * 参数 config：包含维度 ID、列、行、排序状态和排序回调的配置对象。
 * 返回值：包含 Vue 应用与销毁方法的控制对象。
 */
export function mountAnalysisVxeTable(target, config) {
  unmountAnalysisVxeTable();
  const tableId = config.id || "default";
  const isTree = tableId === "traffic";
  const data = isTree
    ? prepareTrafficRows(config.rows || [])
    : prepareFlatRows(config.rows || [], tableId);
  const normalTableHeight = Math.min(380, Math.max(180, 48 + Math.min(data.length, 8) * 39));

  const AnalysisTable = {
    name: "AnalysisVxeTable",
    setup() {
      const shellRef = ref();
      const tableRef = ref();
      const isExpanded = ref(false);
      const tableHeight = ref(normalTableHeight);

      const recalculate = async () => {
        await nextTick();
        await tableRef.value?.recalculate?.(true);
      };

      /**
       * 功能说明：同步表格放大窗口状态，并重新计算表格可用高度。
       * 参数 active：是否打开居中放大窗口。
       * 返回值：Promise；表格尺寸重算完成后结束。
       */
      const syncExpandedState = async (active) => {
        isExpanded.value = active;
        tableHeight.value = active
          ? Math.min(620, Math.max(window.innerHeight - 180, 260))
          : normalTableHeight;
        document.body.classList.toggle("has-analysis-modal", active);
        await recalculate();
      };

      /**
       * 功能说明：打开或关闭当前表格的居中放大窗口。
       * 参数：无。
       * 返回值：Promise；放大窗口状态切换完成后结束。
       */
      const toggleExpanded = async () => {
        await syncExpandedState(!isExpanded.value);
      };

      const handleResize = () => {
        if (isExpanded.value) {
          syncExpandedState(true);
        }
      };
      const handleKeydown = (event) => {
        if (event.key === "Escape" && isExpanded.value) {
          syncExpandedState(false);
        }
      };
      document.addEventListener("keydown", handleKeydown);
      window.addEventListener("resize", handleResize);

      onBeforeUnmount(() => {
        document.removeEventListener("keydown", handleKeydown);
        window.removeEventListener("resize", handleResize);
        document.body.classList.remove("has-analysis-modal");
      });

      const columns = (config.columns || []).map((column, columnIndex) => {
        const props = {
          field: column.key,
          title: column.label,
          minWidth: columnWidth(column, columnIndex, tableId),
          fixed: columnIndex === 0 ? "left" : undefined,
          sortable: true,
          treeNode: isTree && columnIndex === 0,
          showOverflow: "title",
          showHeaderOverflow: "title"
        };
        return h(VxeColumn, props, {
          default: ({ row }) => h("span", {
            class: valueTone(row[column.key], column),
            title: formatTableValue(row[column.key], column.unit || "")
          }, formatTableValue(row[column.key], column.unit || ""))
        });
      });

      return () => h("div", { class: "analysis-vxe-host" }, [
        isExpanded.value
          ? h("button", {
            class: "analysis-modal-backdrop",
            type: "button",
            "aria-label": "关闭完整数据对比放大窗口",
            onClick: () => syncExpandedState(false)
          })
          : null,
        h("section", {
          ref: shellRef,
          class: ["analysis-vxe-shell", { "is-modal-open": isExpanded.value }],
          role: isExpanded.value ? "dialog" : undefined,
          "aria-modal": isExpanded.value ? "true" : undefined,
          "aria-label": isExpanded.value ? "完整数据对比放大窗口" : undefined,
          "data-table-id": tableId
        }, [
          h("header", { class: "analysis-vxe-toolbar" }, [
            h("p", { class: "section-title" }, "完整数据对比"),
            h("button", {
              class: "analysis-expand-button",
              type: "button",
              title: isExpanded.value ? "关闭放大窗口" : "放大查看",
              "aria-label": isExpanded.value ? "关闭完整数据对比放大窗口" : "放大查看完整数据对比",
              onClick: toggleExpanded
            }, [expandIcon(isExpanded.value)])
          ]),
          h("div", { class: "analysis-vxe-stage" }, [
            h(VxeTable, {
            ref: tableRef,
            data,
            height: tableHeight.value,
            size: "small",
            border: "inner",
            stripe: true,
            round: true,
            showOverflow: "title",
            showHeaderOverflow: "title",
            emptyText: "没有符合条件的数据",
            rowConfig: { keyField: "id", isHover: true },
            columnConfig: { resizable: true },
            treeConfig: isTree ? {
              transform: true,
              rowField: "id",
              parentField: "parent_id",
              expandAll: true,
              showLine: false,
              trigger: "cell"
            } : undefined,
            sortConfig: {
              trigger: "cell",
              remote: false,
              isDeep: isTree,
              showIcon: true,
              allowClear: true,
              defaultSort: config.sortState?.key ? {
                field: config.sortState.key,
                order: config.sortState.direction
              } : undefined
            },
            scrollX: { enabled: true, gt: 8 },
            scrollY: { enabled: true, gt: 40 },
            onSortChange: ({ field, order }) => config.onSortChange?.(
              order ? { key: field, direction: order } : null
            )
            }, { default: () => columns })
          ])
        ])
      ]);
    }
  };

  const app = createApp(AnalysisTable);
  app.use(VxeUITable);
  app.mount(target);
  mountedTable = {
    app,
    destroy() {
      app.unmount();
      target.replaceChildren();
    }
  };
  return mountedTable;
}

/**
 * 功能说明：销毁当前正式看板中的 VXE-Table Vue 实例。
 * 参数：无。
 * 返回值：无。
 */
export function unmountAnalysisVxeTable() {
  mountedTable?.destroy();
  mountedTable = null;
}
