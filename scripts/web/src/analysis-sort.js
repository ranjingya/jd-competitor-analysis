const DEFAULT_TREE_CHILDREN_FIELD = "_X_ROW_CHILD";

/**
 * 功能说明：判断表格值是否应固定排在有效数据之后。
 * 参数 value：待判断的原始单元格值。
 * 返回值：短横线、空值、null、非有限数值和数值零返回 true，其余返回 false。
 */
export function isBottomSortValue(value) {
  if (value == null || value === "" || String(value).trim() === "-") {
    return true;
  }
  const number = Number(value);
  return (typeof value === "number" || /^[-+]?\d+(?:\.\d+)?$/.test(String(value).trim()))
    && (!Number.isFinite(number) || number === 0);
}

/**
 * 功能说明：比较两个表格值，并让无效值和零值在升降序中始终沉底。
 * 参数 left：左侧待比较值。
 * 参数 right：右侧待比较值。
 * 参数 order：排序方向，asc 为升序，desc 为降序。
 * 返回值：符合 Array.sort 约定的负数、零或正数。
 */
export function compareTableValues(left, right, order = "asc") {
  const leftBottom = isBottomSortValue(left);
  const rightBottom = isBottomSortValue(right);
  if (leftBottom !== rightBottom) {
    return leftBottom ? 1 : -1;
  }
  if (leftBottom) {
    return 0;
  }

  const leftNumber = Number(left);
  const rightNumber = Number(right);
  const bothNumbers = Number.isFinite(leftNumber) && Number.isFinite(rightNumber);
  const comparison = bothNumbers
    ? leftNumber - rightNumber
    : String(left).localeCompare(String(right), "zh-CN", { numeric: true });
  return order === "desc" ? -comparison : comparison;
}

/**
 * 功能说明：按 VXE 当前排序列整理表格行；树形数据只比较同一父节点下的兄弟节点。
 * 参数 data：VXE 提供的当前平级行或树形根节点数组。
 * 参数 sortList：VXE 当前生效的排序字段与方向列表。
 * 参数 childrenField：树形子节点字段；普通表格传 null。
 * 返回值：排序后的新数组，行对象保持原引用。
 */
export function sortRowsWithBottomValues(
  data,
  sortList,
  childrenField = DEFAULT_TREE_CHILDREN_FIELD
) {
  const activeSort = sortList?.[0];
  const field = activeSort?.field || activeSort?.property;
  const order = activeSort?.order;
  if (!field || !order || !Array.isArray(data)) {
    return data;
  }

  const sortLevel = (rows) => {
    const sortedRows = [...rows].sort((left, right) => (
      compareTableValues(left?.[field], right?.[field], order)
    ));
    if (childrenField) {
      sortedRows.forEach((row) => {
        if (Array.isArray(row?.[childrenField])) {
          row[childrenField] = sortLevel(row[childrenField]);
        }
      });
    }
    return sortedRows;
  };

  return sortLevel(data);
}
