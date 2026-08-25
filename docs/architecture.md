# 系统架构

## 组件职责

| 组件 | 职责 |
|---|---|
| Web | 展示看板并通过同源 `/api` 查询报告。 |
| Backend API | 持续提供报告查询和健康检查，不执行长时间分析请求。 |
| Backend CLI | 读取飞书与 StarRocks，执行确定性计算和 DeepSeek 分析，保存最终报告。 |
| 宿主机 cron | 按固定时间在 Backend 容器中启动一次 CLI 进程。 |
| Healthchecks | 记录日报批次开始、成功、失败和末尾错误日志。 |
| Traefik | 为 Web 提供域名、HTTPS 和入口路由。 |

FastAPI 和 CLI 是 Backend 容器中的独立进程，共享 `/app/data/data.db`。分析任务不通过浏览器或普通 API 请求触发。

## 数据流

```text
宿主机 cron
  → 上报 Healthchecks 开始状态
  → Backend CLI 读取 product-images.json 并同步已有报告主图
  → 获取飞书商品对
  → 检查昨天起最近七天的完整报告缺口
  → 持续更新 daily-analysis-status.json 的阶段和商品对进度
  → 对报告缺口读取飞书映射与 StarRocks 日数据
  → 校验五张来源表都有本品和竞品记录
  → SKU→SPU 与日数据标准化
  → data.db 按模块保存不可变日数据集
  → 确定性分析报告
  → AI 执行记录进入 processing
  → DeepSeek V4 Pro 生成优缺点双摘要、发现和建议
  → Backend 校验结构化结果
  → 原子保存 AI 原始结果并更新报告分析字段
  → 报告状态更新为 ready
  → Web 通过 /api 展示
  → 上报 Healthchecks 成功或失败状态
```

不同商品对依次串行执行。调用 DeepSeek 期间不持有 SQLite 事务；单个商品对失败时记录 `failed` 和 `ai_failed`，随后继续下一组。五张来源表缺少本品或竞品记录时保留报告缺口，不调用 DeepSeek。数仓并发错误在其他商品对处理结束后定向重试。

## API

```text
GET  /api/product-pairs
GET  /api/analysis-status
GET  /api/reports/periods
GET  /api/reports/trends
GET  /api/reports/{report_id}
GET  /api/reports/{report_id}/skus
GET  /api/reports/{granularity}/{start_date}/{end_date}
```

商品对接口只返回每个组合在日、周、月粒度下的最新报告及报告数量。周期选择器按当前月份或年份查询可用报告；趋势接口只返回四项核心指标。完整报告按 `report_id` 加载，也可使用数据库中的 `start_date` 和 `end_date` 精确定位，日报的两个日期相同。SKU 接口返回生成报告时保存的数据集快照，周报和月报按来源日报合并并去重。报告 API 只读取 Backend 数据库。AI 执行记录由 CLI 直接管理，不对外提供领取、完成或失败接口。

## 持久化

- `data/data.db`：按模块保存的标准化日数据、AI 执行状态和最终看板报告。
- `data/daily-analysis-status.json`：当前或最近一次日报批次的原子状态快照。
- `data/product-images.json`：按商品 SPU 维护的 HTTPS 主图地址，由 Backend CLI 同步到报告主图字段。
- StarRocks：业务事实来源，不保存应用的 AI 执行状态。

服务器通过 Docker volume 将宿主机 `data/` 挂载到 Backend 的 `/app/data`。数据库和商品主图配置都由宿主机持久化，Web 容器不直接挂载或读取该目录，只通过 Backend API 获取报告。

## 定时执行

宿主机 cron 每天 12:00 执行：

```cron
0 12 * * * /home/yatui/jd-competitor-analysis/scripts/run-daily-analysis.sh
```

宿主机 `.env` 使用 `HEALTHCHECKS_PING_URL` 保存检查地址。脚本通过 Backend 容器执行 `warehouse-daily-run --yesterday`，日志写入 `data/logs/`。普通运行异常等待 30 秒后整体重试一次；数仓并发上限由 CLI 对受影响商品对按 30、60、120 秒定向重试。

CLI 使用 `/app/data/warehouse-daily-run.lock` 进程锁。同一任务仍在运行时，后续触发直接退出，避免重复读取数仓和覆盖报告。定时模式检查最近七天，已有完整报告直接跳过，仅处理报告缺口。

Backend API 通过 `GET /api/analysis-status` 读取状态快照。任务在配置加载、飞书商品对读取、报告缺口检查、数仓读取、数据集持久化、确定性分析、DeepSeek 分析和报告完成时更新 `progress_at`。进程锁冲突使用专用非零退出码，宿主机脚本向 Healthchecks 上报失败，不将未执行的批次标记为成功。

手动修改宿主机 `data/product-images.json` 后，可以等待下一次日任务，也可以立即执行：

```bash
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py sync-product-images
```
