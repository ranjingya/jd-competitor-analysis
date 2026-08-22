const granularities = ["day", "week", "month"];

function compareReportEntries(left, right) {
  return String(left.start_date || "").localeCompare(String(right.start_date || ""))
    || String(left.end_date || "").localeCompare(String(right.end_date || ""))
    || String(left.updated_at || "").localeCompare(String(right.updated_at || ""))
    || String(left.report_id || "").localeCompare(String(right.report_id || ""));
}

/**
 * 功能说明：把商品对接口转换为页面内部使用的轻量导航状态。
 * 参数 payload：Backend 返回的商品对、最新报告和报告数量。
 * 返回值：包含商品对和各粒度最新报告的页面索引对象。
 */
export function indexFromProductPairs(payload) {
  const reports = { day: [], week: [], month: [] };
  const pairs = (payload?.items || []).map((item) => {
    const pair = {
      key: `${item.self_spu}::${item.competitor_spu}`,
      selfSpu: String(item.self_spu),
      competitorSpu: String(item.competitor_spu),
      selfName: String(item.self_name || "").trim(),
      selfImageUrl: String(item.self_image_url || "").trim(),
      competitorName: String(item.competitor_name || "").trim(),
      competitorImageUrl: String(item.competitor_image_url || "").trim(),
      reportCounts: { day: 0, week: 0, month: 0, ...(item.report_counts || {}) }
    };
    for (const granularity of granularities) {
      const entry = item.latest_reports?.[granularity];
      if (entry) reports[granularity].push(entry);
    }
    return pair;
  });
  for (const granularity of granularities) {
    reports[granularity].sort(compareReportEntries);
  }
  return { updated_at: payload?.updated_at || null, pairs, reports };
}

/**
 * 功能说明：生成商品对在前端状态中的稳定唯一标识。
 * 参数 entry：包含本品和竞品 SPU 的报告索引条目。
 * 返回值：由本品 SPU 与竞品 SPU 组成的唯一字符串。
 */
export function reportPairKey(entry) {
  const selfSpu = String(entry?.self_spu || "").trim();
  const competitorSpu = String(entry?.competitor_spu || "").trim();
  return selfSpu && competitorSpu ? `${selfSpu}::${competitorSpu}` : "";
}

/**
 * 功能说明：整理报告索引中可供用户选择的商品对。
 * 参数 index：Backend 返回的报告索引对象。
 * 返回值：按本品和竞品 SPU 排序的唯一商品对数组。
 */
export function reportPairs(index) {
  if (Array.isArray(index?.pairs)) {
    return index.pairs;
  }
  const pairs = new Map();
  for (const granularity of granularities) {
    for (const entry of index?.reports?.[granularity] || []) {
      const key = reportPairKey(entry);
      if (!key) continue;
      const existing = pairs.get(key);
      pairs.set(key, {
        key,
        selfSpu: String(entry.self_spu),
        competitorSpu: String(entry.competitor_spu),
        selfName: String(entry.self_name || existing?.selfName || "").trim(),
        selfImageUrl: String(
          entry.self_image_url || existing?.selfImageUrl || ""
        ).trim(),
        competitorName: String(
          entry.competitor_name || existing?.competitorName || ""
        ).trim(),
        competitorImageUrl: String(
          entry.competitor_image_url || existing?.competitorImageUrl || ""
        ).trim()
      });
    }
  }
  return [...pairs.values()].sort((left, right) =>
    left.selfSpu.localeCompare(right.selfSpu)
      || left.competitorSpu.localeCompare(right.competitorSpu)
  );
}

/**
 * 功能说明：返回指定商品对的导航信息。
 * 参数 index：页面轻量导航状态。
 * 参数 pairKey：商品对唯一标识。
 * 返回值：商品对对象；不存在时返回 null。
 */
export function reportPair(index, pairKey) {
  return reportPairs(index).find((pair) => pair.key === pairKey) || null;
}

/**
 * 功能说明：合并一个日历上下文内的报告条目并保持稳定时间顺序。
 * 参数 index：页面轻量导航状态。
 * 参数 granularity：day、week 或 month。
 * 参数 pairKey：商品对唯一标识。
 * 参数 context：日报/周报月份 YYYY-MM，或月报年份 YYYY。
 * 参数 entries：当前上下文的报告条目。
 * 返回值：无；直接更新 index 中相应粒度的轻量条目。
 */
export function mergePeriodEntries(index, granularity, pairKey, context, entries) {
  const contextLength = granularity === "month" ? 4 : 7;
  const retained = (index?.reports?.[granularity] || []).filter((entry) =>
    reportPairKey(entry) !== pairKey
      || String(entry.start_date || "").slice(0, contextLength) !== context
  );
  const byId = new Map(
    [...retained, ...(entries || [])].map((entry) => [entry.report_id, entry])
  );
  index.reports[granularity] = [...byId.values()].sort(compareReportEntries);
}

/**
 * 功能说明：读取指定粒度且属于当前商品对的报告。
 * 参数 index：Backend 返回的报告索引对象。
 * 参数 granularity：day、week 或 month。
 * 参数 pairKey：当前选中的商品对唯一标识。
 * 返回值：当前商品对在指定粒度下的报告数组。
 */
export function reportsForPair(index, granularity, pairKey) {
  return (index?.reports?.[granularity] || [])
    .filter((entry) => reportPairKey(entry) === pairKey);
}

/**
 * 功能说明：生成只包含当前商品对的周期选择器索引。
 * 参数 index：完整报告索引对象。
 * 参数 pairKey：当前选中的商品对唯一标识。
 * 返回值：保留索引元信息并过滤三个粒度报告的对象。
 */
export function indexForPair(index, pairKey) {
  return {
    ...index,
    reports: Object.fromEntries(
      granularities.map((granularity) => [
        granularity,
        reportsForPair(index, granularity, pairKey)
      ])
    )
  };
}

/**
 * 功能说明：选择默认打开的商品对，优先使用最新日报。
 * 参数 index：Backend 返回且已按日期升序整理的报告索引对象。
 * 返回值：最新日报或其他最新报告所属的商品对标识。
 */
export function defaultPairKey(index) {
  const latestDay = index?.reports?.day?.at(-1);
  if (latestDay) return reportPairKey(latestDay);
  for (const granularity of ["week", "month"]) {
    const latest = index?.reports?.[granularity]?.at(-1);
    if (latest) return reportPairKey(latest);
  }
  return "";
}
