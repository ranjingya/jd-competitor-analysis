# 京东竞品分析

本项目是一个前后端分离的竞品分析系统。服务器运行 Web 与 Backend 两个容器；宿主机定时启动 Backend CLI，依次完成数仓读取、确定性计算、DeepSeek 分析和报告入库。

## 目录

```text
web/      Vite 看板与内部 Nginx
backend/  FastAPI、批处理、StarRocks 访问、DeepSeek 调用和数据持久化
docs/     数据、估算、报告和看板契约
scripts/  宿主机定时执行脚本
```

## 本地运行

复制根目录 `.env.example` 为 `.env`，然后启动后端：

```bash
uv run --project backend uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

另一个终端启动前端：

```bash
cd web
npm ci
npm run dev
```

前端只访问同源 `/api`。Vite 开发服务器将该路径转发到 `127.0.0.1:8000`；生产环境由 Web 容器内的 Nginx 转发到 Backend 容器。

## 商品主图配置

商品主图在运行数据目录的 `data/product-images.json` 中按商品 ID 维护：

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-08-21",
  "products": {
    "商品 ID": {
      "name": "商品名称",
      "image_url": "https://example.com/product.jpg"
    }
  }
}
```

`image_url` 使用完整 HTTPS 地址，可以直接手动增加或修改。商品没有配置主图时，报告正常生成，Web 使用缺图占位。日分析任务启动时读取一次该文件，先将新地址同步到已有报告，再使用同一份配置生成当天报告。

需要立即同步已有报告时执行：

```bash
backend/.venv/bin/python backend/cli.py sync-product-images
```

## 部署

服务器部署目录保存：

```text
.env
docker-compose.yaml
data/
  data.db
  daily-analysis-status.json
  product-images.json
scripts/
  run-daily-analysis.sh
```

启动服务：

```bash
docker compose up -d
```

两个服务都只使用 Docker 网络中的 `expose`，不直接向宿主机发布端口。Traefik 只连接 Web 容器，Backend 通过内部网络接受 `/api` 转发。

服务器 `.env` 由 Docker Compose 读取并注入 Backend 进程，同时供宿主机日报脚本读取 Healthchecks 地址。Backend 容器不挂载 `.env` 文件，运行时直接读取进程环境变量。

## 定时分析任务

日报由 Backend CLI 在独立进程中执行：

```text
飞书与 StarRocks → 标准化 → 固定公式 → DeepSeek → 最终报告
```

生产环境由宿主机 cron 使用 `docker compose exec` 启动 CLI。FastAPI 持续提供只读报告接口，不通过 Web 请求触发长时间分析。

`.env` 配置 Healthchecks 检查地址：

```dotenv
HEALTHCHECKS_PING_URL=https://hc-cron.kktree.cn/ping/<检查 UUID>
```

部署用户执行一次 `crontab -e`，每天 12:00 启动宿主机脚本：

```cron
0 12 * * * /home/yatui/jd-competitor-analysis/scripts/run-daily-analysis.sh
```

脚本上报开始、成功和失败状态，运行日志保存在 `data/logs/`。所有日志时间统一使用 `Asia/Shanghai`。DeepSeek 每次成功响应的 Token 用量、基础价格快照和估算费用按月追加到 `data/logs/deepseek-usage-YYYY-MM.jsonl`，不保存提示词或业务正文。定时任务按商品对依次检查昨天及此前六天：已有完整报告直接跳过，报告缺口重新查询数仓，同一本品的 SKU 映射在本次进程内复用。商品对在五张来源表中存在任意记录时生成报告，缺失模块和指标按数仓事实保留为空；商品对五张表全部为空时跳过。主业务日期的全部商品对均为空时上报数据异常。

每周一在日报完成后聚合上一个自然周，每月 1 日在日报和周报完成后聚合上一个自然月。周报和月报只读取 `data.db` 中状态为 `ready` 的日报，不再读取数仓。金额、人数和次数累加；转化率按累计成交人数除以累计访客数重算；客单价按累计成交金额除以累计成交人数重算；占比按周期累计分子和分母重算。缺失日报记录在报告元数据中，日均值始终除以自然周期天数。

查看当前运行阶段和最近进度：

```bash
curl -fsS https://jd-comp.skills.kktree.cn/api/analysis-status
```

也可以在服务器直接读取：

```bash
python3 -m json.tool data/daily-analysis-status.json
```

状态包含 `run_id`、容器 PID、当前日期、当前商品对、处理阶段、完成数量、总数量和 `progress_at`。API 同时计算 `process_alive`、`progress_age_seconds` 和 `stale`；进程不存在或业务进度超过 15 分钟没有变化时，`stale` 为 `true`。DeepSeek 阶段允许覆盖两次 300 秒请求超时。任务成功或失败后状态固定为 `completed` 或 `failed`。

## 已有能力

- Web 通过商品对、按需周期、轻量趋势和完整报告 API 展示看板。
- Backend 已提供报告查询 API 和完整日分析 CLI。
- 标准化日数据、AI 执行记录和看板报告统一保存在 `data/data.db`。
- 日数据与报告按业务模块拆分保存，完整报告接口由数据库字段实时组装。
- 同一日期和商品对只有一份当前报告及一条非过期 AI 执行记录。
- StarRocks 连接探测和确定性分析逻辑统一位于 Backend。
- `warehouse-daily-run` 固定一个商品对检查最近七天，再处理下一个商品对。
- `weekly-report-run` 和 `monthly-report-run` 聚合已完成日报并各调用一次 DeepSeek。
- 定时任务自动检查最近七天报告缺口，晚到数据在后续运行中补齐。
- 数仓并发上限错误按 30、60、120 秒定向重试，普通批次异常整体重试一次。
- Healthchecks 记录日周月报告批次的开始、成功、失败及末尾错误日志。
- `/api/analysis-status` 和 `data/daily-analysis-status.json` 提供日报实时阶段与进度快照。
- 商品主图由宿主机 `data/product-images.json` 维护，日任务自动同步到已有报告。
- 日分析使用进程锁防止同一服务器重复执行，单个商品对失败后继续处理下一组。
