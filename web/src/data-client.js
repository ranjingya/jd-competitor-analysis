const reportCache = new Map();

async function readJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`读取失败：${response.status} ${url}`);
  }
  return response.json();
}

/**
 * 功能说明：按周期起止日期和更新时间对报告索引条目升序排列。
 * 参数 left：左侧报告索引条目。
 * 参数 right：右侧报告索引条目。
 * 返回值：供 Array.sort 使用的比较结果。
 */
function compareReportEntries(left, right) {
  return String(left.start_date || "").localeCompare(String(right.start_date || ""))
    || String(left.end_date || "").localeCompare(String(right.end_date || ""))
    || String(left.updated_at || "").localeCompare(String(right.updated_at || ""))
    || String(left.report_id || "").localeCompare(String(right.report_id || ""));
}

/**
 * 功能说明：补齐报告索引的三个粒度，并将每组报告整理为由旧到新的稳定顺序。
 * 参数 index：Backend 返回的报告索引对象。
 * 返回值：字段完整且顺序稳定的报告索引对象。
 */
export function normalizeReportIndex(index) {
  index.reports ||= { day: [], week: [], month: [] };
  for (const granularity of ["day", "week", "month"]) {
    index.reports[granularity] = [...(index.reports[granularity] || [])]
      .sort(compareReportEntries);
  }
  return index;
}

/**
 * 功能说明：读取日、周、月报告索引。
 * 返回值：包含三个粒度报告条目的索引对象。
 */
export async function loadReportIndex() {
  return normalizeReportIndex(await readJson("/api/reports"));
}

/**
 * 功能说明：按索引条目读取一份分析结果，并缓存已加载报告。
 * 参数 entry：包含 `report_id` 和 `path` 的报告索引条目。
 * 返回值：对应报告的完整看板对象。
 */
export async function loadReport(entry) {
  const cacheKey = entry.report_id || entry.path;
  if (reportCache.has(cacheKey)) {
    return reportCache.get(cacheKey);
  }
  const report = await readJson(entry.path);
  reportCache.set(cacheKey, report);
  return report;
}
