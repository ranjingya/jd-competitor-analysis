const reportCache = new Map();

async function readJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`读取失败：${response.status} ${url}`);
  }
  return response.json();
}

/**
 * 功能说明：读取日、周、月报告索引。
 * 返回值：包含三个粒度报告条目的索引对象。
 */
export async function loadReportIndex() {
  const index = await readJson("/reports/report-index.json");
  index.reports ||= { day: [], week: [], month: [] };
  for (const granularity of ["day", "week", "month"]) {
    index.reports[granularity] ||= [];
  }
  return index;
}

/**
 * 功能说明：按索引条目读取一份分析结果，并缓存已加载报告。
 * 参数 entry：包含 `period_key` 和 `path` 的报告索引条目。
 * 返回值：对应周期的 `analysis_result.json` 对象。
 */
export async function loadReport(entry) {
  const cacheKey = entry.period_key || entry.path;
  if (reportCache.has(cacheKey)) {
    return reportCache.get(cacheKey);
  }
  const report = await readJson(entry.path);
  reportCache.set(cacheKey, report);
  return report;
}
