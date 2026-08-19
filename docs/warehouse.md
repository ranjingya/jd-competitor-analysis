# 数仓连接

## 定位

数仓接入先通过只读探测确认网络、账号、驱动和目标表可访问。连接探测不会生成分析结果，也不改变数仓数据；正式数据映射在字段和业务口径确认后接入分析流程。

## 环境变量

项目根目录的 `.env` 保存实际连接参数且不进入版本控制，`.env.example` 保存可提交的字段模板。

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

竞品侧按 `dt + compare_number` 查询。`compare_number` 的固定格式为：

```text
<本品 SPU>+<竞品 SPU>
```

系统使用一个连接顺序读取以下五张表，避免超过数仓并发限制：

```text
ods_rpa_jdzy_competitor_data_compare_f
ods_rpa_jdzy_traffic_source_compare_f
ods_rpa_jdzy_traffic_keyword_compare_f
ods_rpa_jdzy_deal_customer_compare_f
ods_rpa_jdzy_promotion_data_compare_f
```

本品侧先以飞书应用身份只读查询 SPU/SKU 映射，再从 `ods_rpa_jd_jd_business_product_detail_f` 按 `dt + SKU ID` 读取 `natural_day` 数据。同一 SKU 存在多条同步记录时保留 `create_time` 最新的一条，查询层不会把 SPU 当成 SKU。

飞书映射配置：

```dotenv
LARK_APP_ID=<飞书自建应用 App ID>
LARK_APP_SECRET=<飞书自建应用 App Secret>
LARK_BASE_TOKEN=<多维表格 Base Token>
LARK_TABLE_ID=<映射数据表 ID>
LARK_REQUEST_TIMEOUT=30
LARK_PAGE_SIZE=500
```

应用需要获得目标多维表格的只读文档权限，并在开发者后台开通读取多维表格记录所需的应用权限。运行时只调用获取应用凭证和列出记录接口，不调用多维表写入、更新或删除接口。

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
  --compare-number 100174558585+100112260075
```

独立排查飞书映射问题时，可以重复传入 `--sku-id` 临时覆盖映射：

```powershell
uv run --project backend python backend/cli.py warehouse-daily-check `
  --date 2026-08-11 `
  --compare-number 100174558585+100112260075 `
  --sku-id 10001 --sku-id 10002
```

该命令只输出商品对解析结果和各来源记录数量，不输出连接密码或完整业务数据。

## 读取边界

- StarRocks 和飞书多维表操作均只读，按日期和商品标识过滤。
- 五张竞品表顺序读取，不并发占用数仓连接。
- 竞品 `json_data` 必须是 JSON 对象，格式错误时停止当前批次。
- 测试表名只接受数据库标识符及 `数据库.表`、`schema.表` 形式，不接受任意 SQL。
- 样例最多读取 100 行。
- 生产账号应只授予分析所需表的读取权限。
