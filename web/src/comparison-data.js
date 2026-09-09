import { reportPairs, reportsForPair } from "./report-selection.js";
import { buildTrendPoints } from "./trend-data.js";
import { orderAnalysisColumns } from "./analysis-columns.js";

/**
 * 功能说明：取得当前本品的全部有报告竞品，顺序与商品导航一致。
 * 参数 index：报告导航索引；pairKey：当前本品任意一个商品对标识。
 * 返回值：同一本品的商品对数组。
 */
export function comparisonPairs(index, pairKey) {
  const pairs = reportPairs(index);
  const selfSpu = pairs.find((pair) => pair.key === pairKey)?.selfSpu;
  return pairs.filter((pair) => pair.selfSpu === selfSpu);
}

/**
 * 功能说明：合并本品所有竞品的日历条目，同一周期只显示一个入口。
 * 参数 index：报告索引；pairs：本品的商品对数组。
 * 返回值：按日期排序的日、周、月索引，状态保留任一侧的异常。
 */
export function comparisonIndex(index, pairs) {
  return { ...index, reports: Object.fromEntries(["day", "week", "month"].map((grain) => {
    const periods = new Map();
    for (const pair of pairs) for (const entry of reportsForPair(index, grain, pair.key)) {
      const key = `${entry.start_date}:${entry.end_date}`;
      const previous = periods.get(key);
      const status = [previous?.status, entry.status];
      periods.set(key, { ...entry,
        status: status.includes("ai_failed") ? "ai_failed" : status.includes("pending_ai") ? "pending_ai" : entry.status,
        missing_days: [...new Set([...(previous?.missing_days || []), ...(entry.missing_days || [])])]
      });
    }
    return [grain, [...periods.values()].sort((a, b) => a.start_date.localeCompare(b.start_date))];
  })) };
}

/** 合并同一本品的展示值；不同口径的值分开标注，空值不视为零。 */
export function sharedValue(values, unit = "") {
  const available = values.filter((value) => value != null && value !== "" && value !== "-");
  if (!available.length) return null;
  if (available.every((value) => value === available[0])) return available[0];
  return values.map((value, index) => `对竞品 ${index + 1}：${value == null ? "—" : typeof value === "number" ? value.toFixed(2) + unit : value}`).join(" / ");
}

/**
 * 功能说明：按指标 ID 对齐核心数据，保留每个商品对各自的差距和判断。
 * 参数 slots：每项包含 report（可为空）的竞品报告槽位。
 * 返回值：本品展示值和各竞品原始指标组成的数组。
 */
export function comparisonMetrics(slots) {
  const ids = [...new Set(slots.flatMap((slot) => (slot.report?.core_metrics || []).map((metric) => metric.id)))];
  return ids.map((id) => {
    const comparisons = slots.map((slot) => slot.report?.core_metrics?.find((metric) => metric.id === id) || null);
    const metric = comparisons.find(Boolean);
    return { ...metric, self_value: sharedValue(comparisons.map((item) => item?.self_value), metric.unit), comparisons };
  });
}

function rowKey(tab, row) {
  if (tab.id === "traffic") return JSON.stringify([row.level_1, row.level_2, row.level_3].some(Boolean)
    ? [row.level_1 || "", row.level_2 || "", row.level_3 || ""] : [row.path]);
  return JSON.stringify([row[tab.dimension_field] || "", row[tab.columns[0].key]]);
}

/**
 * 功能说明：对齐渠道、关键词和画像的全部行及指标列，保留独有行和空值。
 * 参数 slots：固定顺序的竞品报告槽位，缺失报告保持空槽。
 * 返回值：可供正式表格渲染的合并 Tab；measures 用于切换表格指标。
 */
export function comparisonTabs(slots) {
  const ids = [...new Set(slots.flatMap((slot) => (slot.report?.tabs || []).map((tab) => tab.id)))];
  return ids.map((id) => {
    const tabs = slots.map((slot) => slot.report?.tabs?.find((tab) => tab.id === id));
    const base = tabs.find(Boolean);
    const originals = [...new Map(tabs.flatMap((tab) => tab?.columns || []).map((column) => [column.key, column])).values()];
    const nameColumn = originals[0];
    const selfColumns = originals.filter((column) => column.key.startsWith("self_"));
    const pairedColumns = originals.filter((column) => column.key !== nameColumn.key && !column.key.startsWith("self_"));
    const columns = orderAnalysisColumns([nameColumn, ...selfColumns, ...slots.flatMap((_, index) => pairedColumns.map((column) => ({
      ...column, key: `c${index}_${column.key}`, label: `竞品 ${index + 1} · ${column.label.replace(/^竞品/, "")}`
    })))]);
    const allRows = new Map();
    tabs.forEach((tab, index) => (tab?.rows || []).forEach((row) => {
      const key = rowKey(base, row);
      if (!allRows.has(key)) allRows.set(key, Array(slots.length).fill(null));
      allRows.get(key)[index] = row;
    }));
    const rows = [...allRows.values()].map((sources) => {
      const row = { ...sources.find(Boolean) };
      for (const column of selfColumns) row[column.key] = sharedValue(sources.map((source) => source?.[column.key]), column.unit);
      sources.forEach((source, index) => {
        for (const column of selfColumns) row[`c${index}_${column.key}`] = source?.[column.key] ?? null;
        for (const column of pairedColumns) row[`c${index}_${column.key}`] = source?.[column.key] ?? null;
      });
      return row;
    });
    const measures = selfColumns.map((column) => {
      const suffix = column.key.slice(5);
      const gapKey = ({ visitors: "visitor_gap", gmv: "gmv_gap", conversion_rate_pct: "conversion_gap_pct", rate: "gap_rate" })[suffix];
      const keys = [nameColumn.key, column.key, ...slots.flatMap((_, index) => [
        `c${index}_competitor_${suffix}`, ...(gapKey ? [`c${index}_${gapKey}`] : [])
      ])];
      return { key: column.key, label: column.label.replace(/^本品/, ""), columns: orderAnalysisColumns(keys.map((key) => columns.find((item) => item.key === key)).filter(Boolean)) };
    });
    return { ...base, columns, rows, measures,
      highlightGroups: tabs.map((tab, index) => ({
        competitorLabel: `竞品 ${index + 1}`,
        highlights: [...(tab?.highlights || [])].sort((a, b) => Number(a.status === "warning") - Number(b.status === "warning")),
      })) };
  });
}

/**
 * 功能说明：按时间对齐多个轻量趋势响应；各竞品独立断线，不复制缺失值。
 * 参数 groups：各商品对趋势报告数组；metricId：指标；granularity：粒度；range：时间范围。
 * 返回值：包含本品值和按槽位排列竞品值的统一时间轴。
 */
export function comparisonTrendPoints(groups, metricId, granularity, range) {
  const series = groups.map((reports) => buildTrendPoints(reports, metricId, granularity, range));
  const dates = [...new Set(series.flatMap((points) => points.map((point) => point.periodStart)))].sort();
  return dates.map((date) => {
    const points = series.map((items) => items.find((point) => point.periodStart === date));
    const base = points.find((point) => point?.metric) || points.find(Boolean);
    return { ...base, selfValue: points.find((point) => point?.selfValue != null)?.selfValue ?? null,
      competitorValues: points.map((point) => point?.competitorValue ?? null),
      missing: points.every((point) => !point || point.missing),
      missingCompetitors: points.map((point, index) => point?.competitorValue == null ? `竞品 ${index + 1}` : null).filter(Boolean)
    };
  });
}
