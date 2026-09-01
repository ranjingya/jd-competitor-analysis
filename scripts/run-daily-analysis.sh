#!/usr/bin/env bash

set -uo pipefail

export TZ=Asia/Shanghai

# 根据脚本位置确定部署目录，保证手动执行和 Cron 执行使用同一套路径。
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
LOG_DIR="$PROJECT_DIR/data/logs"
RUN_LOG="$LOG_DIR/daily-analysis-$(date '+%Y-%m-%d').log"
TASK_STARTED_EPOCH="$(date '+%s')"
EXECUTED_REPORT_TYPES="日报"
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
LARK_COMPLETION_WEBHOOK_URL="$(read_env_value LARK_COMPLETION_WEBHOOK_URL)"
LARK_APP_ID="$(read_env_value LARK_APP_ID)"
LARK_APP_SECRET="$(read_env_value LARK_APP_SECRET)"
LARK_ALERT_OPEN_ID="$(read_env_value LARK_ALERT_OPEN_ID)"
LARK_ALERT_READY=1
LARK_COMPLETION_WEBHOOK_READY=1

if [[ -n "$PING_URL" && ! "$PING_URL" =~ ^https?:// ]]; then
  log_message WARNING "HEALTHCHECKS_PING_URL 格式无效，本次任务继续执行但不上报监控状态"
  PING_URL=""
elif [[ -z "$PING_URL" ]]; then
  log_message WARNING "未配置 HEALTHCHECKS_PING_URL，本次任务继续执行但不上报监控状态"
elif ! command -v curl >/dev/null 2>&1; then
  log_message WARNING "宿主机未安装 curl，本次任务继续执行但不上报监控状态"
  PING_URL=""
fi

if [[ -z "$LARK_COMPLETION_WEBHOOK_URL" ]]; then
  LARK_COMPLETION_WEBHOOK_READY=0
elif [[ ! "$LARK_COMPLETION_WEBHOOK_URL" =~ ^https://open\.feishu\.cn/open-apis/bot/v2/hook/ ]]; then
  log_message WARNING "飞书完成通知 Webhook 地址格式无效，本次任务成功时不发送机器人消息"
  LARK_COMPLETION_WEBHOOK_READY=0
elif ! command -v curl >/dev/null 2>&1; then
  log_message WARNING "宿主机未安装 curl，本次任务成功时不发送飞书机器人消息"
  LARK_COMPLETION_WEBHOOK_READY=0
elif ! command -v jq >/dev/null 2>&1; then
  log_message WARNING "宿主机未安装 jq，本次任务成功时不发送飞书机器人消息"
  LARK_COMPLETION_WEBHOOK_READY=0
fi

if [[ -z "$LARK_APP_ID" || -z "$LARK_APP_SECRET" || -z "$LARK_ALERT_OPEN_ID" ]]; then
  log_message WARNING "飞书告警配置不完整，本次任务失败时不发送飞书消息"
  LARK_ALERT_READY=0
elif [[ "$LARK_ALERT_OPEN_ID" != ou_* ]]; then
  log_message WARNING "LARK_ALERT_OPEN_ID 格式无效，本次任务失败时不发送飞书消息"
  LARK_ALERT_READY=0
elif ! command -v curl >/dev/null 2>&1; then
  log_message WARNING "宿主机未安装 curl，本次任务失败时不发送飞书消息"
  LARK_ALERT_READY=0
elif ! command -v jq >/dev/null 2>&1; then
  log_message WARNING "宿主机未安装 jq，本次任务失败时不发送飞书消息"
  LARK_ALERT_READY=0
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

format_duration() {
  # 功能说明：将总秒数转换为简洁的中文耗时文本。
  # 参数 total_seconds：需要格式化的非负秒数。
  # 返回值：通过标准输出返回小时、分钟和秒组成的文本。
  local total_seconds="$1"
  local hours=$((total_seconds / 3600))
  local minutes=$(((total_seconds % 3600) / 60))
  local seconds=$((total_seconds % 60))

  if [[ "$hours" -gt 0 ]]; then
    printf '%s小时%s分%s秒' "$hours" "$minutes" "$seconds"
  elif [[ "$minutes" -gt 0 ]]; then
    printf '%s分%s秒' "$minutes" "$seconds"
  else
    printf '%s秒' "$seconds"
  fi
}

send_lark_completion_webhook() {
  # 功能说明：整个日周月批次成功后，通过飞书群机器人 Webhook 发送一次完成卡片。
  # 参数：无，使用脚本当前批次的执行内容、开始时间和 Webhook 配置。
  # 返回值：始终返回成功；通知异常仅写入运行日志，不改变分析任务退出码。
  local completed_at=""
  local duration_text=""
  local elapsed_seconds=0
  local payload=""
  local api_response=""
  local api_code=""
  local api_message=""

  if [[ "$LARK_COMPLETION_WEBHOOK_READY" -ne 1 ]]; then
    return 0
  fi

  completed_at="$(date '+%Y-%m-%d %H:%M:%S')"
  elapsed_seconds=$(($(date '+%s') - TASK_STARTED_EPOCH))
  duration_text="$(format_duration "$elapsed_seconds")"
  payload="$(
    jq -cn \
      --arg report_types "$EXECUTED_REPORT_TYPES" \
      --arg completed_at "$completed_at" \
      --arg duration "$duration_text" \
      '{
        msg_type: "interactive",
        card: {
          config: {wide_screen_mode: true},
          header: {
            template: "green",
            title: {tag: "plain_text", content: "京东竞品分析任务完成"}
          },
          elements: [
            {
              tag: "div",
              fields: [
                {is_short: false, text: {tag: "lark_md", content: ("**执行内容：** " + $report_types)}},
                {is_short: false, text: {tag: "lark_md", content: ("**完成时间：** " + $completed_at)}},
                {is_short: false, text: {tag: "lark_md", content: ("**总耗时：** " + $duration)}}
              ]
            }
          ]
        }
      }'
  )"

  if ! api_response="$(
    printf '%s' "$payload" | curl -fsS --max-time 10 --retry 3 \
      -H 'Content-Type: application/json; charset=utf-8' \
      --data-binary @- \
      "$LARK_COMPLETION_WEBHOOK_URL"
  )"; then
    log_message WARNING "飞书完成通知发送失败"
    return 0
  fi

  if ! api_code="$(
    jq -r \
      'if has("code") then .code elif has("StatusCode") then .StatusCode else "unknown" end' \
      <<<"$api_response" 2>/dev/null
  )"; then
    log_message WARNING "飞书完成通知返回内容无法解析"
    return 0
  fi
  if [[ "$api_code" != "0" ]]; then
    api_message="$(jq -r '.msg // .StatusMessage // "未知错误"' <<<"$api_response")"
    log_message WARNING "飞书完成通知发送失败：code=$api_code，message=${api_message:0:200}"
    return 0
  fi

  log_message INFO "飞书完成通知发送成功：reports=$EXECUTED_REPORT_TYPES"
}

failure_reason() {
  # 将程序退出码转换为飞书告警使用的简洁原因。
  local exit_code="$1"

  case "$exit_code" in
    "$CONCURRENCY_EXHAUSTED_EXIT_CODE") printf '%s' "数仓并发重试耗尽" ;;
    "$ALREADY_RUNNING_EXIT_CODE") printf '%s' "已有分析任务正在运行" ;;
    "$DAILY_DATA_MISSING_EXIT_CODE") printf '%s' "主业务日期全部商品对均无数仓数据" ;;
    "$AI_PARTIAL_FAILURE_EXIT_CODE") printf '%s' "部分报告 AI 分析失败" ;;
    *) printf '%s' "定时分析任务异常" ;;
  esac
}

send_lark_failure() {
  # 使用飞书自建应用机器人向指定用户发送最终失败通知。
  local exit_code="$1"
  local reason=""
  local log_excerpt=""
  local occurred_at=""
  local server_name=""
  local card_json=""
  local token_response=""
  local tenant_access_token=""
  local api_response=""
  local api_code=""
  local api_message=""

  if [[ "$LARK_ALERT_READY" -ne 1 ]]; then
    return 0
  fi

  reason="$(failure_reason "$exit_code")"
  log_excerpt="$(tail -n 6 "$RUN_LOG" 2>/dev/null || true)"
  if [[ ${#log_excerpt} -gt 1200 ]]; then
    log_excerpt="${log_excerpt: -1200}"
  fi
  if [[ -z "$log_excerpt" ]]; then
    log_excerpt="暂无日志"
  fi
  occurred_at="$(date '+%Y-%m-%d %H:%M:%S')"
  server_name="$(hostname)"
  card_json="$(
    jq -cn \
      --arg occurred_at "$occurred_at" \
      --arg server_name "$server_name" \
      --arg exit_code "$exit_code" \
      --arg reason "$reason" \
      --arg log_excerpt "$log_excerpt" \
      '{
        schema: "2.0",
        config: {
          update_multi: true,
          width_mode: "default",
          summary: {content: "京东竞品分析任务失败"}
        },
        header: {
          title: {tag: "plain_text", content: "京东竞品分析任务失败"},
          template: "red"
        },
        body: {
          direction: "vertical",
          padding: "12px 12px 16px 12px",
          vertical_spacing: "8px",
          elements: [
            {
              tag: "div",
              fields: [
                {is_short: false, text: {tag: "lark_md", content: ("**失败原因：** <font color='red'>" + $reason + "</font>")}},
                {is_short: false, text: {tag: "lark_md", content: ("**时间：** " + $occurred_at)}},
                {is_short: false, text: {tag: "lark_md", content: ("**服务器：** " + $server_name)}},
                {is_short: false, text: {tag: "lark_md", content: ("**退出码：** " + $exit_code)}}
              ]
            },
            {
              tag: "div",
              text: {
                tag: "plain_text",
                content: ("日志摘要：\n" + $log_excerpt),
                text_size: "notation",
                lines: 7
              }
            }
          ]
        }
      }'
  )"

  if ! token_response="$(
    jq -cn \
      --arg app_id "$LARK_APP_ID" \
      --arg app_secret "$LARK_APP_SECRET" \
      '{app_id: $app_id, app_secret: $app_secret}' |
      curl -fsS --max-time 10 \
        -H 'Content-Type: application/json; charset=utf-8' \
        --data-binary @- \
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
  )"; then
    log_message WARNING "飞书 tenant_access_token 获取失败"
    return 0
  fi

  tenant_access_token="$(jq -r 'if .code == 0 then .tenant_access_token // empty else empty end' <<<"$token_response")"
  if [[ -z "$tenant_access_token" ]]; then
    api_code="$(jq -r '.code // "unknown"' <<<"$token_response")"
    api_message="$(jq -r '.msg // "未知错误"' <<<"$token_response")"
    log_message WARNING "飞书 tenant_access_token 获取失败：code=$api_code，message=${api_message:0:200}"
    return 0
  fi

  if ! api_response="$(
    jq -cn \
      --arg receive_id "$LARK_ALERT_OPEN_ID" \
      --argjson card "$card_json" \
      '{receive_id: $receive_id, msg_type: "interactive", content: ($card | tojson)}' |
      curl -fsS --max-time 10 \
        -H "Authorization: Bearer $tenant_access_token" \
        -H 'Content-Type: application/json; charset=utf-8' \
        --data-binary @- \
        'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id'
  )"; then
    unset tenant_access_token
    log_message WARNING "飞书失败通知发送失败"
    return 0
  fi
  unset tenant_access_token

  api_code="$(jq -r '.code // "unknown"' <<<"$api_response")"
  if [[ "$api_code" != "0" ]]; then
    api_message="$(jq -r '.msg // "未知错误"' <<<"$api_response")"
    log_message WARNING "飞书失败通知发送失败：code=$api_code，message=${api_message:0:200}"
    return 0
  fi

  log_message INFO "飞书失败通知发送成功：recipient=$LARK_ALERT_OPEN_ID"
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
  send_lark_failure 1
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
    if [[ "$status" -eq 0 ]]; then
      EXECUTED_REPORT_TYPES="${EXECUTED_REPORT_TYPES}、周报"
    fi
  fi
fi

if [[ "$status" -eq 0 && "$(date '+%d')" == "01" ]]; then
  run_period_with_retry "月报" monthly-report-run --previous-month
  status="$?"
  if [[ "$status" -eq 0 ]]; then
    EXECUTED_REPORT_TYPES="${EXECUTED_REPORT_TYPES}、月报"
  fi
fi

if [[ "$status" -eq 0 ]]; then
  log_message INFO "京东竞品日周月报告任务执行成功"
  ping_healthchecks ""
  send_lark_completion_webhook
else
  log_message ERROR "京东竞品日周月报告任务执行失败：exit_code=$status"
  ping_failure_with_log
  send_lark_failure "$status"
fi

exit "$status"
