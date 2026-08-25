# Backend 数据库设计

## 运行数据位置

Backend 使用一个 SQLite 数据库保存标准化日数据、日周月报告和 DeepSeek 执行记录，并在同一运行数据目录读取商品主图配置：

```text
/app/data/data.db
/app/data/product-images.json
```

本地开发默认使用项目 `data/data.db`，商品主图配置固定使用同目录的 `product-images.json`。运行时可以通过 `BACKEND_DATABASE_PATH` 指定数据库路径，主图配置随数据库目录自动定位。数据目录整体挂载到容器 `/app/data`，Web 只通过 Backend API 读取数据。

数据库结构版本写入 SQLite `PRAGMA user_version`，当前版本为 `2`。应用启动和 CLI 运行时都会初始化当前结构。

```text
analysis_datasets  1 ─── 0..1  reports（日）
                              │
reports（日/周/月） 1 ─── N  analysis_tasks
```

## `analysis_datasets`

保存一个自然日、一个本品 SPU 和一个竞品 SPU 对应的标准化事实版本。数仓和飞书数据进入 Backend 后即按业务模块拆分保存。

| 字段 | 类型 | 用途 |
|---|---|---|
| `dataset_id` | TEXT PRIMARY KEY | 数据集 UUID。 |
| `report_date` | TEXT NOT NULL | 业务日期，格式为 `YYYY-MM-DD`。 |
| `self_spu` | TEXT NOT NULL | 本品 SPU。 |
| `competitor_spu` | TEXT NOT NULL | 竞品 SPU。 |
| `self_product_json` | TEXT NOT NULL | 本品 SKU 五字段映射、SKU 日事实和 SPU 汇总真实值。 |
| `core_metrics_json` | TEXT NOT NULL | 竞品核心指标标准化数据。 |
| `traffic_sources_json` | TEXT NOT NULL | 流量来源标准化数据。 |
| `traffic_keywords_json` | TEXT NOT NULL | 引流关键词标准化数据。 |
| `customer_profile_json` | TEXT NOT NULL | 成交客户画像标准化数据。 |
| `promotion_json` | TEXT NOT NULL | 推广标准化数据。 |
| `source_status_json` | TEXT NOT NULL | Schema 版本、整体质量详情、来源存在状态和扩展审计信息。 |
| `quality_status` | TEXT NOT NULL | `ready`、`partial` 或 `invalid`。 |
| `source_hash` | TEXT NOT NULL | 完整标准化事实的 SHA-256。 |
| `created_at` | TEXT NOT NULL | 数据集创建时间。 |

数据集按内容版本保存。相同 `source_hash` 复用已有 `dataset_id`；同一日期和商品对的内容发生变化时创建新版本。商品对始终使用独立的 `self_spu` 和 `competitor_spu` 字段。

## `reports`

保存 Web 所需的业务报告。同一粒度、日期范围和商品对只有一份报告；大区块使用独立字段，核心指标使用可直接查询的数值字段。

### 身份与周期

| 字段 | 类型 | 用途 |
|---|---|---|
| `report_id` | TEXT PRIMARY KEY | 报告 UUID。 |
| `dataset_id` | TEXT UNIQUE NULL | 日报当前使用的数据集；周报和月报为空。 |
| `granularity` | TEXT NOT NULL | `day`、`week` 或 `month`。 |
| `start_date` | TEXT NOT NULL | 周期开始日期。 |
| `end_date` | TEXT NOT NULL | 周期结束日期。 |
| `self_spu` | TEXT NOT NULL | 本品 SPU。 |
| `competitor_spu` | TEXT NOT NULL | 竞品 SPU。 |
| `source_report_ids_json` | TEXT NOT NULL | 周报和月报使用的来源日报 ID。 |
| `schema_version` | TEXT NOT NULL | 报告 JSON 契约版本。 |

日报的 `start_date` 与 `end_date` 相同。自然周固定为周一至周日。

### 商品与核心指标

| 字段 | 类型 | 用途 |
|---|---|---|
| `self_name` / `competitor_name` | TEXT NULL | 本品和竞品名称。 |
| `self_image_url` / `competitor_image_url` | TEXT NULL | 本品和竞品主图 URL。 |
| `self_gmv` / `competitor_gmv` | REAL NULL | 成交金额。 |
| `self_visitors` / `competitor_visitors` | REAL NULL | 访客数。 |
| `self_buyers` / `competitor_buyers` | REAL NULL | 成交人数。 |
| `self_conversion_rate` / `competitor_conversion_rate` | REAL NULL | 成交转化率，以小数保存。 |
| `self_aov` / `competitor_aov` | REAL NULL | 成交客单价。 |

### 分析与展示模块

| 字段 | 类型 | 用途 |
|---|---|---|
| `advantage_summary` | TEXT NULL | 优点短摘要。 |
| `weakness_summary` | TEXT NULL | 弱点短摘要。 |
| `advantage_detail_json` | TEXT NOT NULL | 优点详情要点数组。 |
| `weakness_detail_json` | TEXT NOT NULL | 弱点详情要点数组。 |
| `ai_findings_json` | TEXT NOT NULL | AI 发现。 |
| `ai_recommendations_json` | TEXT NOT NULL | AI 劣势建议。 |
| `traffic_sources_json` | TEXT NOT NULL | 报告流量来源模块。 |
| `traffic_keywords_json` | TEXT NOT NULL | 报告关键词模块。 |
| `customer_profile_json` | TEXT NOT NULL | 报告客户画像模块。 |
| `promotion_json` | TEXT NOT NULL | 报告推广模块。 |
| `risks_json` | TEXT NOT NULL | 数据风险说明。 |
| `audit_json` | TEXT NOT NULL | 确定性摘要、计算审计和兼容元数据。 |
| `quality_status` | TEXT NOT NULL | 来源数据质量。 |
| `status` | TEXT NOT NULL | `pending_ai`、`ready` 或 `ai_failed`。 |
| `generated_at` | TEXT NULL | 报告数据生成时间。 |
| `created_at` / `updated_at` | TEXT NOT NULL | 创建和更新时间。 |

报告仓库在写入时拆分字段，在完整报告接口读取时组装前端契约。各模块具备独立查询和传输的数据边界。

## `analysis_tasks`

保存 Backend 调用 DeepSeek 的执行记录。任务通过 `report_id` 关联唯一报告，时间范围和商品对由报告提供。

| 字段 | 类型 | 用途 |
|---|---|---|
| `analysis_id` | TEXT PRIMARY KEY | AI 执行记录 UUID。 |
| `report_id` | TEXT NOT NULL | AI 结果最终写入的报告。 |
| `model` | TEXT NOT NULL | 模型标识。 |
| `analysis_version` | TEXT NOT NULL | AI 分析规则版本。 |
| `prompt_hash` | TEXT NOT NULL | 系统提示词 SHA-256。 |
| `source_hash` | TEXT NOT NULL | AI 实际输入、模型、规则版本和提示词的组合哈希。 |
| `payload_json` | TEXT NOT NULL | 本品 SPU 汇总值和五张表的后端处理结果。 |
| `result_json` | TEXT NULL | AI 返回的总结、发现和建议。 |
| `status` | TEXT NOT NULL | `processing`、`completed`、`failed` 或 `expired`。 |
| `attempt_count` | INTEGER NOT NULL | 当前输入的执行次数。 |
| `error_message` | TEXT NULL | 最近一次失败原因。 |
| `created_at` / `updated_at` | TEXT NOT NULL | 创建和更新时间。 |
| `completed_at` | TEXT NULL | 完成时间。 |

同一报告只有一条非 `expired` 记录。已完成且输入不变时直接复用；失败的相同输入复用原记录重试；输入、模型、规则或提示词发生变化时，当前记录标记为 `expired`，然后创建新的执行记录。

## 写入流程

```text
读取 StarRocks 和飞书
  → 标准化本品与五张竞品来源
  → 按模块写入或复用 analysis_datasets
  → 执行确定性公式
  → 按周期和商品对写入唯一 reports，状态 pending_ai
  → 写入 analysis_tasks，状态 processing
  → Backend 调用 DeepSeek
  → 校验并保存 result_json
  → 更新 reports 的摘要、详情、发现和建议字段，状态 ready
```

`quality_status=invalid` 的数据集用于排查，不创建正式报告和 AI 执行记录。`quality_status=partial` 可以继续生成报告；未披露字段保留 `masked/null`。

## 索引与约束

- `analysis_datasets.source_hash` 唯一，保证相同日事实复用。
- `reports(granularity, start_date, end_date, self_spu, competitor_spu)` 唯一，保证一个周期商品对只有一份报告。
- `analysis_tasks(report_id) WHERE status <> 'expired'` 唯一，保证一个报告只有一条当前 AI 执行记录。
- 报告删除时级联删除 AI 执行记录；日报数据集删除时报告的 `dataset_id` 置空。
