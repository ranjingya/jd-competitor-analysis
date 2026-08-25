# 京东竞品分析 MVP 实施计划

## 目标

先跑通一条可用链路：

```text
StarRocks + 飞书映射
  → Backend 标准化日数据
  → data.db
  → DeepSeek V4 Pro 分析
  → Backend API
  → Web 看板
```

当前阶段使用单个 Backend 容器、数仓日数据和宿主机 cron。日报直接分析日数据；周报和月报由已完成日报聚合生成。

## 已完成

- [x] Web、Backend API 和 Backend CLI 完成职责拆分。
- [x] Backend 连接 StarRocks。
- [x] 五张竞品表可以按日期和商品对读取。
- [x] 飞书 Bot 可以实时只读获取 SPU/SKU 映射。
- [x] 飞书多维表提供本品 SPU 和竞品 SPU 候选组合。
- [x] 本品 SKU 日数据可以按映射读取。
- [x] DeepSeek 分析接入 Backend CLI。

## MVP 只使用三张表

完整字段、约束和数据流见 [database-design.md](database-design.md)。

### `analysis_datasets`

保存某一天、某个商品对的标准化数据。

```text
dataset_id
report_date
self_spu
competitor_spu
self_product_json 和五个来源模块 JSON 字段
source_status_json
source_hash
quality_status
created_at
```

### `analysis_tasks`

保存 DeepSeek 执行状态、模型、规则版本、提示词哈希、输入、原始结果和错误信息。所有任务只关联 `report_id`，周期与商品对由报告提供。

### `reports`

保存最终看板数据。

```text
report_id
dataset_id
granularity
start_date
end_date
self_spu
competitor_spu
status
核心指标数值字段
优缺点与 AI 结果字段
四个报告明细模块 JSON 字段
审计与风险字段
created_at
updated_at
```

数据库固定保存在：

```text
/app/data/data.db
/app/data/product-images.json
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

- [x] 将数据库路径统一为 `BACKEND_DATABASE_PATH=/app/data/data.db`。
- [x] 使用 `CREATE TABLE IF NOT EXISTS` 初始化三张表。
- [x] 标准化日数据写入 `analysis_datasets`。
- [x] 使用内容哈希避免相同数据重复写入。
- [x] 标准化日数据按本品与五张来源模块写入 `analysis_datasets`。
- [x] AI 执行记录通过 `report_id` 关联报告。
- [x] 核心指标、AI 结果和报告模块按字段写入 `reports`。

完成标准：Backend 重启后仍能读取数据集、AI 执行记录和报告，不依赖业务 JSON 文件。

## 第三步：跑通一个商品对

- [x] 输入需要处理的日期。
- [ ] 从飞书读取本品 SPU 和竞品 SPU 候选组合；代码已完成，待给 Bot 开通商品对表只读权限。
- [x] 使用独立的本品 SPU 和竞品 SPU 标识商品对。
- [x] 当天核心指标表找不到对应本品与竞品 SPU 时直接跳过该组合。
- [x] 当天核心指标存在时继续处理；其他来源缺失只标记对应模块不可用。
- [x] 从飞书读取本品 SPU 下的 SKU。
- [x] 从 StarRocks 读取五张竞品表和本品 SKU 日数据。
- [x] 本品 SKU 数量、金额等可加总指标汇总到 SPU。
- [x] 生成标准化数据集并写入数据库。
- [x] 执行确定性分析并生成基础报告。
- [x] 创建内部 AI 执行记录并完成模型分析。

完成标准：一个真实商品对能够从数据源走到数据库中的完整报告。

## 第四步：跑通后端 AI

- [x] Backend 根据结构化事实调用 DeepSeek V4 Pro。
- [x] Backend 校验模型返回的总结、发现和建议。
- [x] Backend 保存 AI 结果并生成完整报告。
- [x] 同一报告只保留一个当前任务，新输入使历史任务变为 `expired`。
- [x] AI 失败记录原因并允许下次任务重试。

完成标准：Backend CLI 可以独立完成一次真实分析闭环。

## 第五步：前端只读 API

- [x] `GET /api/product-pairs` 返回商品对、各粒度最新报告和报告数量。
- [x] `GET /api/reports/periods` 按商品对和日历上下文返回可用周期。
- [x] `GET /api/reports/trends` 返回指定范围的四项轻量核心指标。
- [x] `GET /api/reports/{report_id}` 返回完整报告。
- [x] `GET /api/reports/{granularity}/{start_date}/{end_date}` 按数据库周期字段返回完整报告。
- [x] `GET /api/reports/{report_id}/skus` 返回生成报告时的本品 SKU 构成快照。
- [x] Web 首次加载商品对、当前完整报告和轻量趋势。
- [x] Web 在日期选择器展开后加载当前上下文，选择周期后加载完整报告。

完成标准：更新数据库报告后无需重新构建 Web 镜像，页面能够直接展示新结果。

## 第六步：Docker 部署

- [x] Backend 使用宿主机数据目录：

```yaml
volumes:
  - ~/yatui/jd-competitor-analysis/data:/app/data
```

- [ ] `.env` 放在 `~/yatui/jd-competitor-analysis/.env`。
- [x] 商品主图配置保存在宿主机 `data/product-images.json`，日任务自动同步已有报告。
- [ ] Web 和 Backend 保持两个容器。
- [ ] 删除 reports 业务目录挂载。
- [ ] 手动执行一次真实日期分析并检查页面。
- [ ] 宿主机 cron 使用 `--yesterday` 定时启动 Backend CLI。

完成标准：服务器重启或更新镜像后 `data.db` 不丢失，Web 能通过 API 展示报告。

## 第七步：周月聚合

- [x] 报告和 AI 执行表支持日、周、月周期。
- [ ] 周报按周一至周日读取七份完整日报。
- [ ] 月报按自然月读取当月完整日报。
- [ ] 数量和金额指标按日累加。
- [ ] 转化率按累计成交人数除以累计访客数重新计算。
- [ ] 客单价按累计成交金额除以累计成交人数重新计算。
- [ ] 渠道、关键词、画像和推广占比根据累计值重新计算。
- [ ] 周月报告保存来源日报 ID，并进入相同的 DeepSeek 分析流程。

完成标准：指定自然周或自然月能够由完整日报生成唯一报告，并通过 API 与 Web 读取。

## MVP 暂不处理

- 晚到数据自动补算。
- 多后端实例并发。
- 正式数据库迁移框架。
- 独立商品对配置管理。
- 复杂报告版本和历史回滚。
- 自动备份和恢复演练。
- 完整监控告警系统。

这些事项在真实日数据、AI 和 Web 链路全部跑通后再评估。

## 当前运行方式

Backend CLI 从数仓与飞书读取日数据，完成固定公式和 DeepSeek 分析后写入 `data.db`。Web 通过 Backend API 读取报告。
