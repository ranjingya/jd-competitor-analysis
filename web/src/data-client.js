const reportCache = new Map();
const reportSkuCache = new Map();
const reportPeriodCache = new Map();
const reportTrendCache = new Map();

async function readJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`读取失败：${response.status} ${url}`);
  }
  return response.json();
}

/**
 * 功能说明：读取商品对以及每个粒度的最新报告导航信息。
 * 返回值：商品对列表、最新报告和报告数量。
 */
export async function loadProductPairs() {
  return readJson("/api/product-pairs");
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

/**
 * 功能说明：读取指定报告生成时保存的本品 SKU 构成快照。
 * 参数 entry：包含 `report_id` 的报告索引条目。
 * 返回值：包含五字段 SKU 列表和报告周期的对象。
 */
export async function loadReportSkus(entry) {
  const reportId = String(entry?.report_id || "").trim();
  if (!reportId) {
    throw new Error("报告缺少 report_id，无法读取 SKU 构成");
  }
  if (reportSkuCache.has(reportId)) {
    return reportSkuCache.get(reportId);
  }
  const data = await readJson(`/api/reports/${encodeURIComponent(reportId)}/skus`);
  reportSkuCache.set(reportId, data);
  return data;
}

/**
 * 功能说明：按商品对、粒度和日历上下文读取可用报告。
 * 参数 pair：包含 selfSpu 和 competitorSpu 的商品对。
 * 参数 granularity：day、week 或 month。
 * 参数 context：日报/周报月份 YYYY-MM，或月报年份 YYYY。
 * 返回值：当前上下文的轻量报告条目和可导航上下文。
 */
export async function loadReportPeriods(pair, granularity, context) {
  const params = new URLSearchParams({
    self_spu: pair.selfSpu,
    competitor_spu: pair.competitorSpu,
    granularity,
    context
  });
  const url = `/api/reports/periods?${params}`;
  if (!reportPeriodCache.has(url)) {
    reportPeriodCache.set(url, readJson(url));
  }
  return reportPeriodCache.get(url);
}

/**
 * 功能说明：读取指定范围内四项核心指标的轻量趋势数据。
 * 参数 pair：包含 selfSpu 和 competitorSpu 的商品对。
 * 参数 granularity：day、week 或 month。
 * 参数 startDate：趋势开始日期。
 * 参数 endDate：趋势结束日期。
 * 返回值：只包含周期元数据和核心指标的报告数组。
 */
export async function loadReportTrends(pair, granularity, startDate, endDate) {
  const params = new URLSearchParams({
    self_spu: pair.selfSpu,
    competitor_spu: pair.competitorSpu,
    granularity,
    start_date: startDate,
    end_date: endDate
  });
  const url = `/api/reports/trends?${params}`;
  if (!reportTrendCache.has(url)) {
    reportTrendCache.set(url, readJson(url));
  }
  return reportTrendCache.get(url);
}
