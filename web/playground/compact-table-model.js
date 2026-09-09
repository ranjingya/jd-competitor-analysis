const numberFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });

export function formatValue(value, unit = "") {
  return Number.isFinite(value) ? `${numberFormat.format(value)}${unit === "%" ? "%" : ""}` : "—";
}

/**
 * 功能说明：生成本品相对单个竞品的差距展示，保留缺失值及零值含义。
 * 参数 self：本品数值；competitor：竞品数值；unit：指标单位。
 * 返回值：含数值差距、相对幅度或百分点、语义颜色的展示对象。
 */
export function compareValues(self, competitor, unit) {
  if (!Number.isFinite(self) || !Number.isFinite(competitor)) return { primary: "—", secondary: "数据不全", tone: "neutral" };
  const delta = Math.round((self - competitor) * 1e8) / 1e8;
  const signed = (value) => `${value > 0 ? "+" : ""}${numberFormat.format(value)}`;
  return {
    primary: delta === 0 ? "持平" : `${signed(delta)}${unit === "%" ? " pct" : ""}`,
    secondary: unit === "%" || delta === 0 ? "" : competitor === 0 ? "基数为 0" : `${signed(delta / competitor * 100)}%`,
    tone: delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral",
  };
}

/**
 * 功能说明：按预览场景选取三方值，不把无报告竞品填成零。
 * 参数 values：本品及竞品数值数组；scene：dual、single 或 missing。
 * 返回值：展示数值的新数组，单竞品为两项，缺报告保留第三个空槽。
 */
export function sceneValues(values, scene) {
  return scene === "single" ? values.slice(0, 2) : [values[0], values[1], scene === "missing" ? null : values[2]];
}
