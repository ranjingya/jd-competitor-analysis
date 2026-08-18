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

## 当前边界

- 仅支持只读连通性和样例读取，不参与正式分析。
- 测试表名只接受数据库标识符及 `数据库.表`、`schema.表` 形式，不接受任意 SQL。
- 样例最多读取 100 行。
- 生产账号应只授予分析所需表的读取权限。
