/**
 * 功能说明：识别使用蓝色表头的计算、判断与占比列。
 * 参数 column：包含字段名 key 和标题 label 的列定义。
 * 返回值：是否为计算列；用于统一表头颜色与列排序。
 */
export function isDerivedColumn(column) {
  const key = String(column.key || "");
  const label = String(column.label || "");
  return key === "judgement"
    || key === "opportunity"
    || label.includes("判断")
    || /(gap|差距|visitor_gap|gmv_gap|order_gap|gap_rate)/.test(key)
    || label.includes("差距")
    || key.includes("current_level")
    || key.includes("visitor_share")
    || label.includes("访客占比");
}

/**
 * 功能说明：保留名称首列，将蓝色计算列稳定排列在原始数据列之前。
 * 参数 columns：待展示的列数组，第一列为渠道、关键词或画像名称。
 * 返回值：新列数组，各分组内保持原顺序，不修改传入数组。
 */
export function orderAnalysisColumns(columns) {
  if (!columns.length) return [];
  const [name, ...values] = columns;
  return [name, ...values.filter(isDerivedColumn), ...values.filter((column) => !isDerivedColumn(column))];
}
