# 数仓连接

## 定位

数仓接入先通过只读探测确认网络、账号、驱动和目标表可访问。连接探测不会生成分析结果，也不改变数仓数据；正式数据映射在字段和业务口径确认后接入分析流程。

## 环境变量

项目根目录的 `.env` 保存实际连接参数且不进入版本控制，`.env.example` 保存可提交的字段模板。

正式日分析还需要配置 DeepSeek：

```dotenv
DEEPSEEK_API_KEY=<API Key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_TIMEOUT_SECONDS=300
DEEPSEEK_MAX_ATTEMPTS=2
```

项目数仓为 StarRocks，使用 MySQL 协议连接：

```dotenv
DB_DRIVER=mysql+pymysql
DB_HOST=<StarRocks 地址>
DB_PORT=9030
DB_NAME=<数据库名>
DB_USER=<只读账号>
DB_PASSWORD=<密码>
```

`9030` 是 StarRocks 常用查询端口，实际使用自定义端口时以数仓配置为准。

也可以只设置 `DB_URL`。完整 URL 优先于分项参数；密码含 `@`、`:` 或 `/` 等特殊字符时优先使用分项参数，避免自行转义错误。

探测参数：

```dotenv
DB_CONNECT_TIMEOUT=10
DB_TEST_TABLE=ods_rpa_jdzy_competitor_data_compare_f
DB_TEST_LIMIT=5
```

## 执行

```powershell
uv run --project backend python backend/cli.py warehouse-probe
```

临时覆盖目标表和样例行数：

```powershell
uv run --project backend python backend/cli.py warehouse-probe `
  --table ods_rpa_jdzy_traffic_source_compare_f --limit 3
```

命令先执行 `SELECT 1`，然后对目标表执行带 `LIMIT` 的读取。成功输出包含数据库方言、列名和样例行；日志不会输出连接密码。

## 正式日数据来源

竞品侧使用独立的本品 SPU、竞品 SPU、周期起止日期和粒度查询。日任务统一使用 `day`：

```text
spu_id              = 本品 SPU
competitor_spu_id   = 竞品 SPU
start_dt            = 业务日期
dt                  = 业务日期
time_granularity    = day
```

数仓以 `is_competitor=本品/竞品` 将双方拆成独立记录。本品记录的 `competitor_spu_id` 为空，竞品记录包含目标竞品 SPU。

系统使用一个连接顺序读取以下五张表，避免超过数仓并发限制：

```text
ods_rpa_jdzy_competitor_data_compare_f
ods_rpa_jdzy_traffic_source_compare_f
ods_rpa_jdzy_traffic_keyword_compare_f
ods_rpa_jdzy_deal_customer_compare_f
ods_rpa_jdzy_promotion_data_compare_f
```

本品侧先以飞书应用身份只读查询 SPU/SKU 映射，再从 `ods_rpa_jd_jd_business_product_detail_f` 按 `dt + SKU ID` 读取日数据。项目内部粒度统一为 `day`，数仓适配器在查询本品 SKU 表时映射为该表实际使用的 `natural_day`。同一 SKU 存在多条同步记录时保留 `create_time` 最新的一条。

飞书映射配置：

```dotenv
LARK_APP_ID=<飞书自建应用 App ID>
LARK_APP_SECRET=<飞书自建应用 App Secret>
LARK_ALERT_OPEN_ID=<当前飞书应用下的通知接收人 open_id>
LARK_BASE_TOKEN=<多维表格 Base Token>
LARK_TABLE_ID=<映射数据表 ID>
LARK_PAIR_TABLE_ID=<商品对数据表 ID>
LARK_REQUEST_TIMEOUT=30
LARK_PAGE_SIZE=500
```

应用需要获得目标多维表格的只读文档权限，并在开发者后台开通读取多维表格记录和 `im:message:send_as_bot` 权限。通知接收人需要位于应用可用范围内，并已与机器人建立可发送消息的关系。`LARK_ALERT_OPEN_ID` 必须由当前 `LARK_APP_ID` 查询得到。映射流程只调用获取应用凭证和列出记录接口，不调用多维表写入、更新或删除接口；宿主机脚本仅在定时分析最终失败时向该用户发送一张单聊告警卡片。

映射读取固定保留五个业务字段：

```text
主商品条码 -> spu_id
子商品条码 -> sku_id
69码       -> barcode_69
商品名称   -> product_name
规格       -> specification
```

只读检查一个 SPU 的映射：

```powershell
uv run --project backend python backend/cli.py lark-mapping-check `
  --spu-id 100174558585
```

检查指定商品对的五张竞品表、飞书映射和本品 SKU 日数据：

```powershell
uv run --project backend python backend/cli.py warehouse-daily-check `
  --date 2026-08-11 `
  --self-spu 100174558585 `
  --competitor-spu 100112260075
```

独立排查飞书映射问题时，可以重复传入 `--sku-id` 临时覆盖映射：

```powershell
uv run --project backend python backend/cli.py warehouse-daily-check `
  --date 2026-08-11 `
  --self-spu 100174558585 `
  --competitor-spu 100112260075 `
  --sku-id 10001 --sku-id 10002
```

该命令只输出商品对解析结果和各来源记录数量，不输出连接密码或完整业务数据。

执行指定日期的正式分析并写入 `data.db`：

```powershell
uv run --project backend python backend/cli.py warehouse-daily-run `
  --date 2026-08-17 `
  --self-spu 100174558585 `
  --competitor-spu 100112260075
```

不提供 `--self-spu` 和 `--competitor-spu` 时，程序从 `LARK_PAIR_TABLE_ID` 对应的商品对表读取全部候选。两个参数必须同时提供。

服务器定时任务可使用昨天作为业务日期：

```bash
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py warehouse-daily-run --yesterday
```

`--yesterday` 模式以昨天为主业务日期，同时由近到远检查此前六天。同一日期和商品对已有 `ready` 报告时直接跳过；没有完整报告时重新查询数据源。显式 `--date` 用于人工重跑指定日期，会重新执行该商品对并更新同一份业务报告。

手动生成指定自然周或上一个自然周：

```bash
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py weekly-report-run --start-date 2026-08-17

docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py weekly-report-run --previous-week
```

手动生成指定自然月或上一个自然月：

```bash
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py monthly-report-run --month 2026-08

docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py monthly-report-run --previous-month
```

周报和月报只聚合 `data.db` 中状态为 `ready` 的日报。周期报告保存来源日报 ID、自然周期天数、可用日报天数和缺失日期。数量、金额和次数累加；转化率、客单价、渠道占比、关键词占比和画像占比使用周期累计值重新计算。周期日均值使用自然周 7 天或自然月实际天数作为分母。

## 服务器手动命令速查

以下命令均在 `/home/yatui/jd-competitor-analysis` 执行：

```bash
cd /home/yatui/jd-competitor-analysis

# 完整执行与 Cron 相同的日周月定时流程，并上报 Healthchecks
/bin/bash scripts/run-daily-analysis.sh

# 指定一天的全部飞书商品对
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py warehouse-daily-run --date YYYY-MM-DD

# 指定一天的一个商品对
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py warehouse-daily-run --date YYYY-MM-DD \
  --self-spu SELF_SPU --competitor-spu COMPETITOR_SPU

# 指定自然周的全部商品对；start-date 必须是周一
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py weekly-report-run --start-date YYYY-MM-DD

# 指定自然周的一个商品对
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py weekly-report-run --start-date YYYY-MM-DD \
  --self-spu SELF_SPU --competitor-spu COMPETITOR_SPU

# 指定自然月的全部商品对
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py monthly-report-run --month YYYY-MM

# 指定自然月的一个商品对
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py monthly-report-run --month YYYY-MM \
  --self-spu SELF_SPU --competitor-spu COMPETITOR_SPU
```

上一个完整自然周使用 `weekly-report-run --previous-week`，上一个完整自然月使用 `monthly-report-run --previous-month`。周报和月报只聚合数据库中已有的 `ready` 日报，不读取数仓；需要补日报时先逐日执行 `warehouse-daily-run --date`。所有分析命令共用任务锁，不能并行执行。

## 日报生成门槛

数仓记录是日报的业务事实来源。一个商品对在以下五张来源表中存在任意记录时，后端按实际内容继续生成报告：

```text
核心指标
流量来源
引流关键词
成交客户画像
推广数据
```

来源表、商品角色或指标缺失时保持固定空结构，质量状态为 `partial`，现有数据继续进入确定性分析和 DeepSeek。字段值为 `null`、`masked` 或 `0`，以及双方维度项不完全一致，均按数仓事实处理。商品对在五张表中全部没有记录时跳过报告；同一业务日期的全部商品对均没有记录时标记整日数据异常。

日报批次按以下方式处理运行异常：

- 单个商品对五张来源表全部为空：跳过当前商品对，不立即重试，后续七天缺口检查再次读取。
- 主业务日期的全部商品对均为空：使用专用非零退出码上报告警，不执行普通整体重试。
- 数仓并发达到上限：继续处理其他商品对，随后只对受影响商品对按 30、60、120 秒加 0–10 秒随机抖动重试。
- DeepSeek 网络异常：在当前商品对请求内有限重试；模型结果不符合 JSON 契约时只重新生成当前分析一次。
- DeepSeek 最终失败：报告和执行记录标记为 `ai_failed`，继续其他商品对；批次结束后使用专用非零退出码上报告警，不执行普通整体重试。
- 其他运行异常：宿主机脚本等待 30 秒后整体重试一次；已有完整报告在定时模式中直接跳过。
- 数仓并发定向重试耗尽或整体重试仍失败：命令返回失败，由 Healthchecks 标记该批次异常。
- 已有日报进程持有任务锁：命令使用专用非零退出码结束，不触发整体重试，并由 Healthchecks 标记异常。

## 运行状态

日报 CLI 在共享数据目录维护 `daily-analysis-status.json`，并由 Backend API 提供同一份只读状态：

```bash
curl -fsS https://jd-comp.skills.kktree.cn/api/analysis-status
```

主要字段：

```text
status           idle、running、completed 或 failed
stage            当前处理阶段
run_id           本次运行唯一 ID
pid              容器内 CLI 进程 PID
primary_date     主业务日期
dates            本次检查的业务日期
current_date     当前业务日期
self_spu         当前本品 SPU
competitor_spu   当前竞品 SPU
completed_items  已结束的日期商品对数量
total_items      日期商品对总数
progress_at      最近业务进度时间
completed_at     成功或失败结束时间
error            失败类型和摘要
process_alive    容器内任务进程是否仍存在
progress_age_seconds 最近业务进度距当前的秒数
stale            进程不存在或超过 15 分钟没有业务进度
```

`progress_at` 只在业务阶段推进时更新。DeepSeek 最长允许两次 300 秒请求；超过 15 分钟没有新进度时，应结合 `stage`、运行日志和容器进程检查外部请求是否卡住。

商品对表和 SPU/SKU 映射表都需要向飞书应用开放只读权限。用户账号能够读取多维表，不代表 Bot 应用身份自动拥有相同权限。

## 读取边界

- StarRocks 和飞书多维表操作均只读，按日期和商品标识过滤。
- 五张竞品表顺序读取，不并发占用数仓连接。
- 竞品 `json_data` 必须是 JSON 对象，格式错误时停止当前批次。
- 每张表的 `json_data` 字段名会与当前适配字段集合比较；字段新增、缺失或改名时记录 WARNING 和数据质量问题。
- 测试表名只接受数据库标识符及 `数据库.表`、`schema.表` 形式，不接受任意 SQL。
- 样例最多读取 100 行。
- 生产账号应只授予分析所需表的读取权限。
