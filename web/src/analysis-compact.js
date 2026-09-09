const GAP_KEYS = { visitors: "visitor_gap", gmv: "gmv_gap", conversion_rate_pct: "conversion_gap_pct", rate: "gap_rate" };

/**
 * 功能说明：合并本品指标与各竞品差距为纵排列，竞品原值置于末尾，保留文字判断。
 * 参数 columns：当前指标筛选后的合并列；count：固定顺序的竞品槽位数量。
 * 返回值：紧凑表格列定义，原始输入保持不变。
 */
export function compactColumns(columns, count) {
  const selfColumns = columns.filter((column) => column.key.startsWith("self_"));
  if (!count || !selfColumns.length) return columns;
  const metrics = selfColumns.map((column) => ({ ...column, label: column.label.replace(/^本品/, ""), kind: "metric", count,
    suffix: column.key.slice(5), gapKey: GAP_KEYS[column.key.slice(5)] }));
  const coveredGaps = new Set(metrics.flatMap((column) => Array.from({ length: count }, (_, index) => `c${index}_${column.gapKey}`)));
  const raw = columns.filter((column) => /^c\d+_competitor_/.test(column.key))
    .map((column) => ({ ...column, kind: "raw" }))
    .sort((left, right) => Number(left.key.match(/^c(\d+)_/)[1]) - Number(right.key.match(/^c(\d+)_/)[1]));
  const remaining = columns.slice(1).filter((column) => !column.key.startsWith("self_") && !raw.some((item) => item.key === column.key) && !coveredGaps.has(column.key));
  const textColumns = [...new Set(remaining.map((column) => column.key.replace(/^c\d+_/, "")))].map((key) => {
    const first = remaining.find((column) => column.key.replace(/^c\d+_/, "") === key);
    return { ...first, key: `compact_${key}`, sourceKey: key, label: first.label.replace(/^竞品 \d+ · /, ""), kind: "comparison", count };
  });
  const judgements = textColumns.filter((column) => column.sourceKey === "judgement");
  return [columns[0], { key: "compact_roles", label: "对比", kind: "roles", count }, ...judgements, ...metrics,
    ...textColumns.filter((column) => column.sourceKey !== "judgement"), ...raw];
}

/** 简化判断列的本品前缀，其他状态和缺失值保持原样。 */
export function compactJudgement(value) {
  return typeof value === "string" ? value.replace(/^本品(?=领先|落后)/, "") : value;
}

/**
 * 功能说明：取得一个商品对的展示差距，优先使用报告计算结果，缺失值不当作零。
 * 参数 row：含各商品对独立本品值的合并行；column：紧凑指标列；index：竞品槽位序号。
 * 返回值：差值、单位、相对百分比和零基数标记。
 */
export function compactDifference(row, column, index) {
  const self = row[`c${index}_${column.key}`];
  const competitor = row[`c${index}_competitor_${column.suffix}`];
  const unit = column.unit === "%" ? "pct" : column.unit || "";
  if (!Number.isFinite(self) || !Number.isFinite(competitor)) return { value: null, unit, percent: null, zeroBase: false };
  const stored = column.gapKey ? row[`c${index}_${column.gapKey}`] : null;
  const value = Number.isFinite(stored) ? stored : Math.round((self - competitor) * 1e8) / 1e8;
  return { value, unit, percent: column.unit !== "%" && competitor !== 0 ? value / competitor * 100 : null,
    zeroBase: column.unit !== "%" && competitor === 0 && value !== 0 };
}

/**
 * 功能说明：为紧凑指标和文字判断生成独立排序值，支持按本品或指定竞品的差距排序。
 * 参数 rows：完整表格行；columns：紧凑列定义；basis：self 或竞品槽位序号字符串。
 * 返回值：包含排序辅助字段的新行数组。
 */
export function compactSortRows(rows, columns, basis) {
  return rows.map((row) => {
    const result = { ...row };
    for (const column of columns) {
      if (column.kind === "metric") result[`sort_${column.key}`] = basis === "self"
        ? (Number.isFinite(row[column.key]) ? row[column.key] : null)
        : compactDifference(row, column, Number(basis)).value;
      if (column.kind === "comparison") result[`sort_${column.key}`] = row[`c${basis === "self" ? 0 : basis}_${column.sourceKey}`] ?? null;
    }
    return result;
  });
}

/** 按当前列类型取得排序字段，普通原值列使用自身字段。 */
export function compactSortField(columns, key) {
  return ["metric", "comparison"].includes(columns.find((column) => column.key === key)?.kind) ? `sort_${key}` : key;
}

/**
 * 功能说明：把紧凑列按差距、竞品槽位组织为二层表头，固定身份列独立跨行。
 * 参数 columns：紧凑列定义。
 * 返回值：固定列与分组列数组，子列保留原字段，竞品编号保持稳定。
 */
export function compactColumnGroups(columns) {
  if (!columns.some((column) => column.kind === "metric")) return columns;
  const fixed = columns.filter((column) => !["metric", "comparison", "raw"].includes(column.kind));
  const gaps = { key: "compact_gaps", label: "差距", kind: "group", derived: true,
    children: columns.filter((column) => ["metric", "comparison"].includes(column.kind)) };
  const raw = new Map();
  for (const column of columns.filter((item) => item.kind === "raw")) {
    const index = Number(column.key.match(/^c(\d+)_/)[1]);
    if (!raw.has(index)) raw.set(index, { key: `compact_competitor_${index}`, label: `竞品 ${index + 1}`, kind: "group", children: [] });
    raw.get(index).children.push({ ...column, label: column.label.replace(/^竞品 \d+ · /, "") });
  }
  return [...fixed, gaps, ...raw.values()];
}
