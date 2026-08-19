# 京东竞品分析 MVP 实施计划

## 目标

先跑通一条可用链路：

```text
StarRocks + 飞书映射
  → Backend 标准化日数据
  → backend.db
  → Mac Codex 分析
  → Backend API
  → Web 看板
```

当前阶段只支持单个后端容器、日数据和手动触发。周月聚合、自动调度、复杂版本管理和多实例部署在 MVP 跑通后处理。

## 已完成

- [x] Web、Backend、Mac AI Worker 完成职责拆分。
- [x] Backend 连接 StarRocks。
- [x] 五张竞品表可以按日期和商品对读取。
- [x] 飞书 Bot 可以实时只读获取 SPU/SKU 映射。
- [x] 飞书多维表提供本品 SPU 和竞品 SPU 候选组合。
- [x] 本品 SKU 日数据可以按映射读取。
- [x] AI 任务领取和回传 API 具备基础框架。

## MVP 只使用三张表

完整字段、约束和数据流见 [database-design.md](database-design.md)。

### `analysis_datasets`

保存某一天、某个商品对的标准化数据。

```text
dataset_id
report_date
self_spu
competitor_spu
source_hash
payload_json
quality_status
created_at
```

### `analysis_tasks`

保存 AI 任务、租约和 AI 回传结果，沿用现有表并关联 `dataset_id`。

### `reports`

保存最终看板数据。

```text
report_id
dataset_id
status
report_json
created_at
updated_at
```

数据库固定保存在：

```text
/app/data/backend.db
```

暂不建立商品对配置表、运行记录表、独立 AI 结果表和迁移框架。

## 第一步：统一日数据

- [x] 定义简单公共结构：日期、商品对、来源、记录和质量状态。
- [x] 将区间值统一解析成 `raw`、`status`、`low`、`high`、`unit`，不在标准化阶段生成估算值。
- [x] 五张竞品表转换成稳定英文键。
- [x] 同类记录始终包含相同字段；缺失字段统一补为 `masked`。
- [x] 客户画像缺占比时补齐固定字段，并按实际可用情况标记质量状态。
- [x] 最新批次内部按原始 `id` 升序恢复记录顺序。
- [x] 补充五类转换器的必要测试。
- [x] 将飞书映射中的本品 SKU 与数仓日记录转换为固定结构。
- [x] 按业务口径将本品 SKU 加总为 SPU，并重新计算转化率和客单价。
- [x] 将本品 SPU 和五张竞品来源组装为完整标准化日数据。

完成标准：指定日期和商品对能够生成一份稳定、可校验的标准化日数据。

## 第二步：保存到 Backend 数据库

- [x] 将数据库路径统一为 `BACKEND_DATABASE_PATH=/app/data/backend.db`。
- [x] 使用 `CREATE TABLE IF NOT EXISTS` 初始化三张表。
- [x] 标准化日数据写入 `analysis_datasets`。
- [x] 使用内容哈希避免相同数据重复写入。
- [x] AI 任务通过 `dataset_id` 关联数据集。
- [x] 最终看板数据写入 `reports`。

完成标准：Backend 重启后仍能读取数据集、AI 任务和报告，不依赖业务 JSON 文件。

## 第三步：跑通一个商品对

- [x] 输入需要处理的日期。
- [ ] 从飞书读取本品 SPU 和竞品 SPU 候选组合；代码已完成，待给 Bot 开通商品对表只读权限。
- [x] 使用 `<本品spu>+<竞品spu>` 生成 `compare_number`。
- [x] 当天核心指标表找不到 `compare_number` 时直接跳过该组合。
- [x] 当天核心指标存在时继续处理；其他来源缺失只标记对应模块不可用。
- [x] 从飞书读取本品 SPU 下的 SKU。
- [x] 从 StarRocks 读取五张竞品表和本品 SKU 日数据。
- [x] 本品 SKU 数量、金额等可加总指标汇总到 SPU。
- [x] 生成标准化数据集并写入数据库。
- [x] 执行现有确定性分析并生成基础报告。
- [x] 创建一条 AI 分析任务。

完成标准：一个真实商品对能够从数据源走到数据库中的待分析报告。

## 第四步：跑通 Mac AI

- [ ] Mac Codex 领取一条任务。
- [ ] AI 根据后端提供的结构化事实生成分析和建议。
- [ ] AI 将结果回传 Backend。
- [x] Backend 保存 AI 结果并生成完整报告。
- [ ] 错误任务可以标记失败并重新人工触发。

完成标准：不使用模型 API，Mac Codex 可以完成一次真实分析闭环。

## 第五步：前端只读 API

- [ ] `GET /api/reports` 从数据库返回报告列表。
- [ ] `GET /api/reports/{report_id}` 返回完整报告。
- [ ] 提供 SPU 组成 SKU 的只读接口。
- [ ] Web 从 API 获取列表和报告详情。
- [ ] Web 不再读取 `report-index.json` 和 `analysis_result.json`。

完成标准：更新数据库报告后无需重新构建 Web 镜像，页面能够直接展示新结果。

## 第六步：Docker 部署

- [ ] Backend 使用宿主机数据目录：

```yaml
volumes:
  - ~/yatui/jd-competitor-analysis/data:/app/data
```

- [ ] `.env` 放在 `~/yatui/jd-competitor-analysis/.env`。
- [ ] Web 和 Backend 保持两个容器。
- [ ] 删除 reports 业务目录挂载。
- [ ] 手动执行一次真实日期分析并检查页面。

完成标准：服务器重启或更新镜像后 `backend.db` 不丢失，Web 能通过 API 展示报告。

## MVP 暂不处理

- 周、月聚合。
- 自动定时任务。
- 晚到数据自动补算。
- 多后端实例并发。
- 正式数据库迁移框架。
- 独立商品对配置管理。
- 复杂报告版本和历史回滚。
- 自动备份和恢复演练。
- 完整监控告警系统。

这些事项在真实日数据、AI 和 Web 链路全部跑通后再评估。

## 下一项工作

使用 Mac Codex 领取现有真实任务，生成 AI 内容并回传 Backend，验证报告状态更新为 `ready`。
