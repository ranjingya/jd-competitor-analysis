# 系统架构

## 组件职责

| 组件 | 职责 |
|---|---|
| Web | 展示看板并通过同源 `/api` 查询报告。 |
| Backend API | 持续提供报告查询和健康检查，不执行长时间分析请求。 |
| Backend CLI | 读取飞书与 StarRocks，执行确定性计算和 DeepSeek 分析，保存最终报告。 |
| 宿主机 cron | 按固定时间在 Backend 容器中启动一次 CLI 进程。 |
| Traefik | 为 Web 提供域名、HTTPS 和入口路由。 |

FastAPI 和 CLI 是 Backend 容器中的独立进程，共享 `/app/data/backend.db`。分析任务不通过浏览器或普通 API 请求触发。

## 数据流

```text
宿主机 cron
  → Backend CLI 获取飞书映射与 StarRocks 日数据
  → SKU→SPU 与日数据标准化
  → backend.db 保存不可变数据集
  → 确定性分析报告
  → AI 执行记录进入 processing
  → DeepSeek V4 Pro 生成总结、发现和建议
  → Backend 校验结构化结果
  → 原子保存 AI 原始结果并合并基础报告
  → 报告状态更新为 ready
  → Web 通过 /api 展示
```

不同商品对依次串行执行。调用 DeepSeek 期间不持有 SQLite 事务；单个商品对失败时记录 `failed` 和 `ai_failed`，随后继续下一组。

## API

```text
GET  /api/reports
GET  /api/reports/{report_id}
GET  /api/reports/{report_id}/skus
GET  /api/reports/{granularity}/{start_date}/{end_date}
```

周期报告接口使用数据库中的 `start_date` 和 `end_date` 精确定位报告；日报的两个日期相同。SKU 接口返回生成报告时保存的数据集快照，周报和月报按来源日报合并并去重。报告 API 只读取 Backend 数据库。AI 执行记录由 CLI 直接管理，不对外提供领取、完成或失败接口。

## 持久化

- `data/backend.db`：标准化数据集、AI 执行状态和最终看板报告。
- StarRocks：业务事实来源，不保存应用的 AI 执行状态。

服务器通过 Docker volume 持久化 `data/`。Web 容器不直接挂载或读取该目录，只通过 Backend API 获取报告。

## 定时执行

宿主机 cron 执行：

```bash
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py warehouse-daily-run --yesterday
```

CLI 使用 `/app/data/warehouse-daily-run.lock` 进程锁。同一任务仍在运行时，后续触发直接退出，避免重复读取数仓和覆盖报告。
