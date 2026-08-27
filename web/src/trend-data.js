function trendPeriodLabel(meta, granularity) {
  const start = String(meta.period_start || "");
  const end = String(meta.period_end || "");
  if (granularity === "month") {
    return start.slice(0, 7) || meta.period || "-";
  }
  if (granularity === "week" && end && end !== start) {
    return `${start.slice(5)}~${end.slice(5)}`;
  }
  return start.slice(5) || meta.period || "-";
}


function isoDatesBetween(startDate, endDate) {
  const dates = [];
  const cursor = new Date(`${startDate}T00:00:00Z`);
  const end = new Date(`${endDate}T00:00:00Z`);
  while (cursor <= end) {
    dates.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return dates;
}


/**
 * 功能说明：把趋势报告转换为完整时间轴，日报缺失日期保留空点以中断折线。
 * 参数 reports：趋势接口返回的轻量报告数组。
 * 参数 metricId：需要绘制的核心指标 ID。
 * 参数 granularity：day、week 或 month。
 * 参数 range：趋势查询的开始和结束日期。
 * 返回值：包含正常点和缺失空点的有序数组。
 */
export function buildTrendPoints(reports, metricId, granularity, range = {}) {
  const reportPoints = reports.map((report) => {
    const metric = (report.core_metrics || []).find((item) => item.id === metricId);
    const periodStart = String(report.meta?.period_start || "");
    return {
      period: report.meta?.period || periodStart || "-",
      periodStart,
      label: trendPeriodLabel(report.meta || {}, granularity),
      selfValue: typeof metric?.self_value === "number" ? metric.self_value : null,
      competitorValue: typeof metric?.competitor_value === "number" ? metric.competitor_value : null,
      metric: metric || null,
      reportStatus: report.report_status || "ready",
      qualityStatus: report.quality_status || "ready",
      missing: false
    };
  });
  if (granularity !== "day" || !range.startDate || !range.endDate) {
    return reportPoints;
  }
  const byDate = new Map(reportPoints.map((item) => [item.periodStart, item]));
  return isoDatesBetween(range.startDate, range.endDate).map((date) => byDate.get(date) || {
    period: date,
    periodStart: date,
    label: date.slice(5),
    selfValue: null,
    competitorValue: null,
    metric: null,
    reportStatus: "missing",
    qualityStatus: "missing",
    missing: true
  });
}


/**
 * 功能说明：生成缺失日期的浅色背景带，使趋势断点在宽屏和窄屏下都清晰可见。
 * 参数 points：包含正常点和缺失空点的完整趋势时间轴。
 * 返回值：ECharts 自定义系列配置；没有缺失日期时返回空值。
 */
export function buildMissingTrendSeries(points) {
  const missingIndexes = points
    .map((item, index) => item.missing ? index : null)
    .filter((index) => index !== null);
  if (!missingIndexes.length) {
    return null;
  }
  const missingRanges = missingIndexes.reduce((ranges, index) => {
    const current = ranges.at(-1);
    if (current && index === current[1] + 1) {
      current[1] = index;
    } else {
      ranges.push([index, index]);
    }
    return ranges;
  }, []);
  return {
    name: "无数据日期",
    type: "custom",
    coordinateSystem: "cartesian2d",
    silent: true,
    animation: false,
    tooltip: { show: false },
    data: missingRanges,
    renderItem(params, api) {
      const startCoordinate = api.coord([api.value(0), 0]);
      const endCoordinate = api.coord([api.value(1), 0]);
      const categoryWidth = Math.abs(api.size([1, 0])[0]);
      const minimumX = params.coordSys.x;
      const maximumX = params.coordSys.x + params.coordSys.width;
      const x = Math.max(minimumX, startCoordinate[0] - categoryWidth * 0.34);
      const right = Math.min(maximumX, endCoordinate[0] + categoryWidth * 0.34);
      const width = Math.max(30, right - x);
      const y = params.coordSys.y;
      const height = params.coordSys.height;
      return {
        type: "group",
        children: [
          {
            type: "rect",
            shape: { x, y, width, height, r: 6 },
            style: { fill: "rgba(176, 160, 132, 0.11)" }
          },
          {
            type: "text",
            style: {
              x: x + width / 2,
              y: y + 9,
              text: "无数据",
              fill: "#8a7c68",
              font: '600 11px Inter, "PingFang SC", sans-serif',
              textAlign: "center",
              textVerticalAlign: "top"
            }
          }
        ]
      };
    }
  };
}
