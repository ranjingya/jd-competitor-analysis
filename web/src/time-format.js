const BEIJING_TIME_ZONE = "Asia/Shanghai";
const BEIJING_DATE_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  timeZone: BEIJING_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23"
});

/**
 * 功能说明：把 API 时间统一格式化为北京时间。
 * 参数 value：带时区信息的 ISO 8601 时间文本。
 * 返回值：`YYYY-MM-DD HH:mm:ss` 格式的北京时间；无效输入返回空字符串。
 */
export function formatBeijingDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = Object.fromEntries(
    BEIJING_DATE_TIME_FORMATTER.formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value])
  );
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}
