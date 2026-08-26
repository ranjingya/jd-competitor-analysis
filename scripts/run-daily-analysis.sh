#!/usr/bin/env bash

set -uo pipefail

export TZ=Asia/Shanghai

# 根据脚本位置确定部署目录，保证手动执行和 Cron 执行使用同一套路径。
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
LOG_DIR="$PROJECT_DIR/data/logs"
RUN_LOG="$LOG_DIR/daily-analysis-$(date '+%Y-%m-%d').log"
GENERAL_RETRY_DELAY_SECONDS=30
CONCURRENCY_EXHAUSTED_EXIT_CODE=11
ALREADY_RUNNING_EXIT_CODE=12
DAILY_DATA_MISSING_EXIT_CODE=13
AI_PARTIAL_FAILURE_EXIT_CODE=14

if ! mkdir -p "$LOG_DIR"; then
  printf '%s ERROR 无法创建日志目录：%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$LOG_DIR" >&2
  exit 1
fi

log_message() {
  # 为宿主机调度日志补充统一时间和级别。
  local level="$1"
  shift
  printf '%s %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$*" | tee -a "$RUN_LOG"
}

read_env_value() {
  # 从 Docker 环境文件中读取单个配置，避免把整份 .env 当作 Shell 脚本执行。
  local key="$1"
  local line=""
  local value=""

  if [[ -f "$ENV_FILE" ]]; then
    line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  fi
  value="${line#*=}"
  value="${value%$'\r'}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"

  if [[ ${#value} -ge 2 ]]; then
    if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]] ||
      [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  printf '%s' "$value"
}

PING_URL="$(read_env_value HEALTHCHECKS_PING_URL)"
PING_URL="${PING_URL%/}"

if [[ -n "$PING_URL" && ! "$PING_URL" =~ ^https?:// ]]; then
  log_message WARNING "HEALTHCHECKS_PING_URL 格式无效，本次任务继续执行但不上报监控状态"
  PING_URL=""
elif [[ -z "$PING_URL" ]]; then
  log_message WARNING "未配置 HEALTHCHECKS_PING_URL，本次任务继续执行但不上报监控状态"
elif ! command -v curl >/dev/null 2>&1; then
  log_message WARNING "宿主机未安装 curl，本次任务继续执行但不上报监控状态"
  PING_URL=""
fi

ping_healthchecks() {
  # 上报任务状态；监控服务异常不能阻断日报主流程。
  local suffix="$1"

  if [[ -z "$PING_URL" ]]; then
    return 0
  fi

  if ! curl -fsS --max-time 10 --retry 3 \
    "$PING_URL$suffix" >/dev/null 2>&1; then
    log_message WARNING "Healthchecks 状态上报失败：suffix=${suffix:-success}"
  fi
}

ping_failure_with_log() {
  # 失败时附带最后一段运行日志，便于从看板直接定位原因。
  if [[ -z "$PING_URL" ]]; then
    return 0
  fi

  if ! tail -c 10000 "$RUN_LOG" | curl -fsS --max-time 10 --retry 3 \
    --data-binary @- "$PING_URL/fail" >/dev/null 2>&1; then
    log_message WARNING "Healthchecks 失败状态上报失败"
  fi
}

run_daily_analysis() {
  # 执行一轮完整日报；成功商品会由后端报告唯一键在下一轮中自动跳过或复用。
  local attempt="$1"
  local command_status

  log_message INFO "开始执行日报批次：attempt=$attempt"
  docker compose exec -T jd-competitor-analysis-backend \
    python /app/cli.py warehouse-daily-run --yesterday \
    2>&1 | tee -a "$RUN_LOG"
  command_status="${PIPESTATUS[0]}"
  log_message INFO "日报批次执行结束：attempt=$attempt，exit_code=$command_status"
  return "$command_status"
}

run_period_analysis() {
  # 执行周期报告命令；周期报告只聚合 data.db 中已完成的日报。
  local label="$1"
  local attempt="$2"
  shift 2
  local command_status

  log_message INFO "开始执行${label}批次：attempt=$attempt"
  docker compose exec -T jd-competitor-analysis-backend \
    python /app/cli.py "$@" \
    2>&1 | tee -a "$RUN_LOG"
  command_status="${PIPESTATUS[0]}"
  log_message INFO "${label}批次执行结束：attempt=$attempt，exit_code=$command_status"
  return "$command_status"
}

run_period_with_retry() {
  # 周期报告普通异常整体重试一次，AI 部分失败和进程锁冲突直接上报告警。
  local label="$1"
  shift
  local period_status

  run_period_analysis "$label" 1 "$@"
  period_status="$?"
  if [[ "$period_status" -ne 0 && "$period_status" -ne "$ALREADY_RUNNING_EXIT_CODE" && \
    "$period_status" -ne "$AI_PARTIAL_FAILURE_EXIT_CODE" ]]; then
    log_message WARNING "${label}批次发生异常，${GENERAL_RETRY_DELAY_SECONDS} 秒后整体重试一次"
    sleep "$GENERAL_RETRY_DELAY_SECONDS"
    run_period_analysis "$label" 2 "$@"
    period_status="$?"
  fi
  return "$period_status"
}

log_message INFO "开始执行京东竞品日报：project_dir=$PROJECT_DIR"
ping_healthchecks "/start"

cd "$PROJECT_DIR" || {
  log_message ERROR "无法进入项目目录：$PROJECT_DIR"
  ping_failure_with_log
  exit 1
}

run_daily_analysis 1
status="$?"

if [[ "$status" -ne 0 && "$status" -ne "$CONCURRENCY_EXHAUSTED_EXIT_CODE" && \
  "$status" -ne "$ALREADY_RUNNING_EXIT_CODE" && \
  "$status" -ne "$DAILY_DATA_MISSING_EXIT_CODE" && \
  "$status" -ne "$AI_PARTIAL_FAILURE_EXIT_CODE" ]]; then
  log_message WARNING "日报批次发生普通异常，${GENERAL_RETRY_DELAY_SECONDS} 秒后整体重试一次"
  sleep "$GENERAL_RETRY_DELAY_SECONDS"
  run_daily_analysis 2
  status="$?"
fi

if [[ "$status" -eq "$AI_PARTIAL_FAILURE_EXIT_CODE" ]]; then
  log_message ERROR "部分报告 AI 分析失败，已保留基础报告且不执行整体重试"
fi

if [[ "$status" -eq 0 ]]; then
  if [[ "$(date '+%u')" == "1" ]]; then
    run_period_with_retry "周报" weekly-report-run --previous-week
    status="$?"
  fi
fi

if [[ "$status" -eq 0 && "$(date '+%d')" == "01" ]]; then
  run_period_with_retry "月报" monthly-report-run --previous-month
  status="$?"
fi

if [[ "$status" -eq 0 ]]; then
  log_message INFO "京东竞品日周月报告任务执行成功"
  ping_healthchecks ""
else
  log_message ERROR "京东竞品日周月报告任务执行失败：exit_code=$status"
  ping_failure_with_log
fi

exit "$status"
