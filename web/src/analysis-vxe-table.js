import { createApp, h, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import VxeButton from "vxe-pc-ui/es/button";
import VxeNumberInput from "vxe-pc-ui/es/number-input";
import VxeRadioGroup from "vxe-pc-ui/es/radio-group";
import VxeUITable, { VxeColumn, VxeColgroup, VxeTable, VxeToolbar } from "vxe-table";
import "vxe-pc-ui/lib/style.css";
import "vxe-table/lib/style.css";
import "./analysis-vxe-table.css";
import { isDerivedColumn } from "./analysis-columns.js";
import { compactColumnGroups, compactColumns, compactDifference, compactSortField, compactSortRows } from "./analysis-compact.js";
import {
  sortFlatTreeRowsBySiblings,
  sortRowsWithBottomValues
} from "./analysis-sort.js";

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
  return typeof value === "number" ? `${value.toFixed(2)}${unit}` : `${value}${String(value).startsWith("对竞品 ") ? "" : unit}`;
}

/**
 * 功能说明：判断当前列是否为需要使用进度条展示的占比列。
 * 参数 column：当前列定义，包含单位等展示信息。
 * 返回值：单位为百分号且列标题包含“占比”时返回 true，转化率和差值列返回 false。
 */
function isProgressColumn(column) {
  return column.unit === "%" && String(column.label || "").includes("占比");
}

/**
 * 功能说明：把百分比值限制在进度条可展示的 0 至 100 范围。
 * 参数 value：当前单元格的原始百分比值。
 * 返回值：有效数值返回限制范围后的结果，无效值返回 null。
 */
function normalizeProgressValue(value) {
  if (value == null || value === "" || value === "-") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? Math.min(100, Math.max(0, number)) : null;
}

/**
 * 功能说明：生成正式表格使用的细进度条与右侧百分比数字。
 * 参数 value：当前单元格的原始百分比值。
 * 参数 column：当前列定义，用于统一数值格式。
 * 返回值：可直接放入 VXE 列插槽的 Vue 虚拟节点。
 */
function renderProgressValue(value, column) {
  const percentage = normalizeProgressValue(value);
  const displayValue = formatTableValue(value, column.unit || "");
  if (percentage == null) {
    return h("span", {
      class: "analysis-value-neutral",
      title: displayValue
    }, displayValue);
  }
  return h("span", {
    class: "analysis-progress-cell",
    title: displayValue,
    "aria-label": `占比 ${displayValue}`
  }, [
    h("span", { class: "analysis-progress-track", "aria-hidden": "true" }, [
      h("span", {
        class: "analysis-progress-fill",
        style: { width: `${percentage}%` }
      })
    ]),
    h("strong", { class: "analysis-progress-value" }, displayValue)
  ]);
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
 * 功能说明：渲染紧凑指标、身份与文字判断的纵排内容，本品值位于首行。
 * 参数 row：合并后的表格行；column：带类型和竞品数量的列定义。
 * 返回值：保持统一行高的 Vue 虚拟节点。
 */
function renderCompactCell(row, column) {
  const roles = Array.from({ length: column.count }, (_, index) => `竞品 ${index + 1}`);
  const line = (content, className = "", label) => h("div", { class: ["analysis-compact-line", className], "aria-label": label }, content);
  if (column.kind === "roles") return h("div", { class: "analysis-compact-labels" }, [line("本品", "is-self"), ...roles.map((role) => line(role))]);
  if (column.kind === "comparison") return h("div", {}, [line("", "is-self"), ...roles.map((role, index) => {
    const value = row[`c${index}_${column.sourceKey}`];
    return line(formatTableValue(value), valueTone(value, column), `${role}：${formatTableValue(value)}`);
  })]);
  const self = row[column.key];
  const selfText = String(self ?? "").startsWith("对竞品 ")
    ? roles.map((role, index) => h("span", { class: "analysis-compact-self-variant" }, [
      h("small", {}, `${role}：`),
      isProgressColumn(column) ? renderProgressValue(row[`c${index}_${column.key}`], column) : formatTableValue(row[`c${index}_${column.key}`], column.unit)
    ]))
    : isProgressColumn(column) ? renderProgressValue(self, column) : formatTableValue(self, column.unit);
  return h("div", { class: "analysis-compact-metric" }, [line(selfText, "is-self", `本品：${formatTableValue(self, column.unit)}`), ...roles.map((role, index) => {
    const gap = compactDifference(row, column, index);
    const signed = (value, unit) => `${value > 0 ? "+" : ""}${formatTableValue(value, unit)}`;
    const primary = gap.value == null ? "—" : signed(gap.value, gap.unit);
    const secondary = gap.zeroBase ? "基数为 0" : gap.percent == null ? "" : signed(gap.percent, "%");
    return line([h("strong", {}, primary), secondary ? h("small", {}, secondary) : null], valueTone(gap.value, { key: "gap" }),
      `本品较${role}：${primary}${secondary ? `，${secondary}` : ""}`);
  })]);
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
  if (column.kind === "roles") return 68;
  if (column.kind === "metric") return 152;
  if (column.kind === "comparison") return 142;
  if (isProgressColumn(column)) {
    return 160;
  }
  if (columnIndex === 1 && String(column.label || "").includes("判断")) {
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
  const columnDefinitions = compactColumns(config.columns || [], config.competitorCount);
  const compact = columnDefinitions.some((column) => column.kind === "metric");
  const initialBasis = config.sortState?.basis || "self";
  const data = isTree
    ? prepareTrafficRows(config.rows || [])
    : prepareFlatRows(config.rows || [], tableId);
  const initialSortList = config.sortState?.key
    ? [{ field: compactSortField(columnDefinitions, config.sortState.key), order: config.sortState.direction }]
    : [];
  const sortedInitialData = isTree
    ? sortFlatTreeRowsBySiblings(compactSortRows(data, columnDefinitions, initialBasis), initialSortList)
    : sortRowsWithBottomValues(compactSortRows(data, columnDefinitions, initialBasis), initialSortList, null);
  const selfHeight = data.some((row) => columnDefinitions.some((column) => column.kind === "metric" && String(row[column.key]).startsWith("对竞品 "))) ? 48 : 28;
  const normalTableHeight = compact ? Math.min(460, Math.max(180, 88 + data.length * (selfHeight + config.competitorCount * 28 + 24)))
    : Math.min(380, Math.max(180, 48 + Math.min(data.length, 8) * 39));

  const AnalysisTable = {
    name: "AnalysisVxeTable",
    setup() {
      const shellRef = ref();
      const tableRef = ref();
      const toolbarRef = ref();
      const isExpanded = ref(false);
      const tableHeight = ref(normalTableHeight);
      const tableData = ref(sortedInitialData);
      const sortBasis = ref(initialBasis);
      let activeSort = config.sortState || null;

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
        document.body.classList.toggle("has-analysis-modal", active);
        await nextTick();
        // 按弹窗实际内容区计算高度，随视口尺寸与响应式内边距同步。
        tableHeight.value = active
          ? Math.max(1, shellRef.value.querySelector(".analysis-vxe-stage").clientHeight)
          : normalTableHeight;
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

      /**
       * 功能说明：接管表格区域的滚轮事件，只滚动 VXE 主体并阻止滚动链传递到页面。
       * 参数 event：表格区域触发的原生滚轮事件。
       * 返回值：无。
       */
      const handleTableWheel = (event) => {
        if (event.ctrlKey || event.metaKey) {
          return;
        }
        if (!(event.target instanceof Element) || !event.target.closest(".vxe-table")) {
          return;
        }
        const scrollBody = event.currentTarget.querySelector(
          ".vxe-table--main-wrapper .vxe-table--body-inner-wrapper"
        );
        if (!scrollBody) {
          return;
        }
        const unit = event.deltaMode === 1
          ? 36
          : event.deltaMode === 2
            ? scrollBody.clientHeight
            : 1;
        const deltaY = event.deltaY * unit;
        const deltaX = event.deltaX * unit;
        if (event.shiftKey && Math.abs(deltaX) < Math.abs(deltaY)) {
          scrollBody.scrollLeft += deltaY;
        } else if (Math.abs(deltaY) >= Math.abs(deltaX)) {
          scrollBody.scrollTop += deltaY;
        } else {
          scrollBody.scrollLeft += deltaX;
        }
        event.preventDefault();
        event.stopPropagation();
      };

      /**
       * 功能说明：连接 VXE 工具栏与当前表格，使列设置入口能够读取并修改列状态。
       * 参数：无。
       * 返回值：Promise；工具栏和表格完成连接后结束。
       */
      const connectColumnToolbar = async () => {
        await nextTick();
        tableRef.value?.connectToolbar?.(toolbarRef.value);
      };

      /**
       * 功能说明：接管 VXE 排序事件，按当前维度生成新行序并保持表格滚动位置。
       * 参数 field：当前排序列字段名。
       * 参数 order：排序方向；null 表示清除排序。
       * 返回值：Promise；数据、尺寸和滚动位置同步完成后结束。
       */
      const handleControlledSort = async (field, order) => {
        const scrollBody = shellRef.value?.querySelector(
          ".vxe-table--main-wrapper .vxe-table--body-inner-wrapper"
        );
        const scrollPosition = {
          left: scrollBody?.scrollLeft || 0,
          top: scrollBody?.scrollTop || 0
        };
        const sortList = order ? [{ field: compactSortField(columnDefinitions, field), order }] : [];
        const sortableData = compactSortRows(data, columnDefinitions, sortBasis.value);
        tableData.value = isTree
          ? sortFlatTreeRowsBySiblings(sortableData, sortList)
          : sortRowsWithBottomValues(sortableData, sortList, null);
        activeSort = order ? { key: field, direction: order, basis: sortBasis.value } : null;
        config.onSortChange?.(activeSort);
        await recalculate();
        const refreshedScrollBody = shellRef.value?.querySelector(
          ".vxe-table--main-wrapper .vxe-table--body-inner-wrapper"
        );
        if (refreshedScrollBody) {
          refreshedScrollBody.scrollLeft = scrollPosition.left;
          refreshedScrollBody.scrollTop = scrollPosition.top;
        }
      };

      document.addEventListener("keydown", handleKeydown);
      window.addEventListener("resize", handleResize);
      onMounted(connectColumnToolbar);

      onBeforeUnmount(() => {
        document.removeEventListener("keydown", handleKeydown);
        window.removeEventListener("resize", handleResize);
        document.body.classList.remove("has-analysis-modal");
      });

      const renderColumn = (column) => {
        if (column.kind === "group") return h(VxeColgroup, {
          key: column.key,
          field: column.key,
          title: column.label,
          headerClassName: column.derived ? "analysis-derived-header" : undefined,
          headerAlign: "center"
        }, { default: () => column.children.map(renderColumn) });
        const columnIndex = columnDefinitions.findIndex((item) => item.key === column.key);
        const stacked = ["roles", "metric", "comparison"].includes(column.kind);
        const props = {
          field: column.key,
          title: column.label,
          minWidth: compact && columnIndex === 0 ? 168 : columnWidth(column, columnIndex, tableId),
          fixed: columnIndex === 0 || column.kind === "roles" ? "left" : undefined,
          sortable: column.kind !== "roles",
          treeNode: isTree && columnIndex === 0,
          headerClassName: column.kind === "metric" || column.kind === "comparison" || (!column.kind && isDerivedColumn(column)) ? "analysis-derived-header" : undefined,
          showOverflow: stacked ? false : "title",
          align: column.kind === "metric" || column.kind === "raw" ? "right" : undefined,
          showHeaderOverflow: "title"
        };
        return h(VxeColumn, props, {
          default: ({ row }) => stacked ? renderCompactCell(row, column) : isProgressColumn(column)
            ? renderProgressValue(row[column.key], column)
            : h("span", {
              class: valueTone(row[column.key], column),
              title: formatTableValue(row[column.key], column.unit || "")
            }, formatTableValue(row[column.key], column.unit || ""))
        });
      };
      const columns = compactColumnGroups(columnDefinitions).map(renderColumn);

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
          style: { "--compact-self-height": `${selfHeight}px` },
          role: isExpanded.value ? "dialog" : undefined,
          "aria-modal": isExpanded.value ? "true" : undefined,
          "aria-label": isExpanded.value ? "完整数据对比放大窗口" : undefined,
          "data-table-id": tableId
        }, [
          h("header", { class: "analysis-vxe-toolbar" }, [
            h("p", { class: "section-title" }, "完整数据对比"),
            h("div", { class: "analysis-vxe-actions" }, [
              compact ? h("label", { class: "analysis-sort-basis" }, ["排序依据", h("select", {
                value: sortBasis.value,
                "aria-label": "多行指标排序依据",
                onChange: (event) => {
                  sortBasis.value = event.target.value;
                  if (activeSort) handleControlledSort(activeSort.key, activeSort.direction);
                }
              }, [h("option", { value: "self" }, "本品值"), ...Array.from({ length: config.competitorCount }, (_, index) => h("option", { value: String(index) }, `较竞品 ${index + 1} 差值`))])]) : null,
              h(VxeToolbar, {
                ref: toolbarRef,
                custom: true,
                perfect: false,
                size: "mini",
                className: "analysis-column-toolbar"
              }),
              h("button", {
                class: "analysis-expand-button",
                type: "button",
                title: isExpanded.value ? "关闭放大窗口" : "放大查看",
                "aria-label": isExpanded.value ? "关闭完整数据对比放大窗口" : "放大查看完整数据对比",
                onClick: toggleExpanded
              }, [expandIcon(isExpanded.value)])
            ])
          ]),
          h("div", {
            class: "analysis-vxe-stage",
            onWheelCapture: handleTableWheel
          }, [
            h(VxeTable, {
            ref: tableRef,
            id: `analysis-vxe-${compact ? "grouped-compact-" : ""}${tableId}-${columnDefinitions.map((column) => column.key).join("-")}`,
            data: tableData.value,
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
            customConfig: {
              mode: "simple",
              trigger: "click",
              immediate: true,
              storage: true,
              allowVisible: true,
              allowFixed: true,
              allowSort: true,
              allowResizable: true,
              allowAlign: false,
              showSortDragButton: true,
              showFooter: true,
              placement: "top-right",
              popupOptions: {
                minWidth: 360,
                maxHeight: 420,
                transfer: false
              }
            },
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
              remote: true,
              showIcon: true,
              allowClear: true,
              defaultSort: config.sortState?.key ? {
                field: config.sortState.key,
                order: config.sortState.direction
              } : undefined
            },
            scrollX: { enabled: true, gt: 8 },
            scrollY: { enabled: !compact, gt: 40 },
            onSortChange: ({ field, order }) => handleControlledSort(field, order)
            }, { default: () => columns })
          ])
        ])
      ]);
    }
  };

  const app = createApp(AnalysisTable);
  app.use(VxeButton);
  app.use(VxeNumberInput);
  app.use(VxeRadioGroup);
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
