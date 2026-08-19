---
name: jd-competitor-ai-worker
description: 领取京东竞品分析后端的待处理任务，基于后端提供的结构化事实生成 AI 总结、发现和运营建议，并把结果安全回传。用于 Mac 上的 Codex 手动任务或定时任务；不负责连接数仓、计算业务指标或维护网页。
---

# 京东竞品 AI Worker

## 工作边界

本 Skill 只在 Mac Codex 中处理后端已经完成确定性计算的分析任务：

1. 从后端领取一条待分析任务。
2. 阅读任务中的结构化事实和风险说明。
3. 按 [analysis-guidelines.md](references/analysis-guidelines.md) 生成总结、发现和建议。
4. 按 [task-api.md](references/task-api.md) 保存临时结果并回传。
5. 回传成功后继续领取，直到后端返回没有待处理任务或达到本次任务上限。

不要连接 StarRocks，不要重新计算 SKU→SPU、日周月聚合、同比环比或准真实估算值。不要修改任务输入中的事实字段、数据版本和风险说明。

## 配置

将 `.env.example` 复制为本目录 `.env`，配置后端地址、访问令牌和当前 Mac 的 Worker 标识。令牌只保存在本机，不写入任务文件、分析结果或日志。

## 领取与回传

先查看最近任务及其 ID、生成时间、状态和商品对：

```bash
python <Skill目录>/scripts/task_client.py list
```

只查看待处理任务：

```bash
python <Skill目录>/scripts/task_client.py list --status pending
```

领取任务：

```bash
python <Skill目录>/scripts/task_client.py claim --output <临时目录>/task.json
```

`task.json` 中的 `task` 为 `null` 时结束。存在任务时，生成符合结果契约的 `<临时目录>/result.json`，然后执行：

```bash
python <Skill目录>/scripts/task_client.py complete \
  --task <临时目录>/task.json \
  --result <临时目录>/result.json
```

只有分析无法完成时才上报失败：

```bash
python <Skill目录>/scripts/task_client.py fail \
  --task <临时目录>/task.json \
  --error <可排查的失败原因>
```

每次运行使用独立临时目录。回传成功后删除任务与结果临时文件；回传失败时保留文件，先判断租约是否仍有效，再决定是否重试。同一任务只提交领取时返回的 `source_hash` 和 `lease_token`。

## 输出要求

- 只陈述任务数据可以支持的事实与判断。
- 明确区分本品真实值和竞品估算值。
- 缺失值不视为零，风险标记为不可用的模块不生成确定性建议。
- 建议必须包含证据、具体动作和可复核的验收条件。
- 不补造预算、资源位、商品卖点、人群结论或预期提升幅度。
- 临时结果必须先完成 JSON 结构检查，再调用完成接口。
