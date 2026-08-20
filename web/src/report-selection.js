const granularities = ["day", "week", "month"];

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
