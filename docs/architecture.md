# 系统架构

## 组件职责

| 组件 | 职责 |
|---|---|
| Web | 展示看板并通过同源 `/api` 查询报告。 |
| Backend | 读取 StarRocks、执行确定性计算、保存报告、创建和管理 AI 任务。 |
| Codex Skill | 在 Mac 上领取结构化任务，生成人工语言分析并回传。 |
| Traefik | 为 Web 提供域名、HTTPS 和入口路由。 |

Backend 不调用模型，服务器也不主动连接 Mac。Mac 只持有 AI Worker 接口令牌，不持有 StarRocks 账号。

## 数据流

```text
StarRocks 日数据
  → Backend SKU→SPU 与日数据标准化
  → backend.db 保存不可变数据集
  → 确定性分析报告
  → AI pending 任务
  → Mac Codex 领取并分析
  → Backend 校验数据哈希和租约
  → 原子保存 AI 结果并合并基础报告
  → 报告状态更新为 ready
  → Web 通过 /api 展示
```

## API

```text
GET  /api/reports
GET  /api/reports/{report_id}
GET  /api/reports/{granularity}/{period}
GET  /api/analysis-tasks
POST /api/analysis-tasks/claim
POST /api/analysis-tasks/{analysis_id}/complete
POST /api/analysis-tasks/{analysis_id}/fail
```

AI 任务接口要求 Bearer Token。列表接口按生成时间倒序返回任务 ID、生成时间、状态和商品对等摘要，可使用 `status` 和 `limit` 查询参数筛选。领取操作原子设置租约，完成操作同时校验 `analysis_id`、`source_hash` 和 `lease_token`。Mac 只提交 `summary`、`findings` 和 `recommendations`；Backend 在同一数据库事务中保存原始 AI 结果、合并完整报告并更新报告状态。

## 持久化

- `data/backend.db`：标准化数据集、AI 任务状态和最终看板报告。
- StarRocks：业务事实来源，不保存 Codex 运行状态。

服务器通过 Docker volume 持久化 `data/`。Web 容器不直接挂载或读取该目录，只通过 Backend API 获取报告。
