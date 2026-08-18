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
  → Backend SKU→SPU 与日周月聚合
  → 确定性分析报告
  → AI pending 任务
  → Mac Codex 领取并分析
  → Backend 校验数据哈希和租约
  → 保存 AI 分析结果
  → Web 通过 /api 展示
```

## API

```text
GET  /api/reports
GET  /api/reports/{granularity}/{period}
POST /api/analysis-tasks/claim
POST /api/analysis-tasks/{analysis_id}/complete
POST /api/analysis-tasks/{analysis_id}/fail
```

AI 任务接口要求 Bearer Token。领取操作原子设置租约，完成操作同时校验 `analysis_id`、`source_hash` 和 `lease_token`。

## 持久化

- `reports/`：后端生成的看板报告。
- `data/analysis-tasks.db`：AI 任务状态、租约和回传结果。
- StarRocks：业务事实来源，不保存 Codex 运行状态。

服务器通过 Docker volume 分别持久化 `data/` 和 `reports/`。Web 容器不直接挂载或读取这两个目录。
