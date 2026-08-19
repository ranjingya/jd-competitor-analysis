# Backend 数据库设计

## 目标

Backend 使用一个 SQLite 数据库保存标准化日数据、DeepSeek 执行记录和最终看板报告：

```text
/app/data/backend.db
```

本地开发默认使用项目 `data/backend.db`。运行时通过 `BACKEND_DATABASE_PATH` 指定数据库位置。

MVP 固定使用三张表：

```text
analysis_datasets  1 ─── N  analysis_tasks
        ↑                    │
        └── 当前版本 ── reports 1 ─── N 历史任务
```

关键词、客户画像、流量来源、推广明细和 SPU/SKU 构成保存在 JSON 字段中，不拆分业务明细表。

## `analysis_datasets`

保存一个自然日、一个本品 SPU 和一个竞品 SPU 对应的标准化事实版本。

| 字段 | SQLite 类型 | 约束 | 用途 |
|---|---|---|---|
| `dataset_id` | TEXT | PRIMARY KEY | 数据集 UUID。 |
| `report_date` | TEXT | NOT NULL | 业务日期，格式为 `YYYY-MM-DD`。 |
| `self_spu` | TEXT | NOT NULL | 本品 SPU。 |
| `competitor_spu` | TEXT | NOT NULL | 竞品 SPU。 |
| `compare_number` | TEXT | NOT NULL | 数仓商品对，格式为 `<本品SPU>+<竞品SPU>`。 |
| `source_hash` | TEXT | NOT NULL, UNIQUE | 完整标准化 JSON 的 SHA-256。 |
| `payload_json` | TEXT | NOT NULL | 完整标准化日数据。 |
| `quality_status` | TEXT | NOT NULL | `ready`、`partial` 或 `invalid`。 |
| `created_at` | TEXT | NOT NULL | 数据集创建时间，使用带时区 ISO 8601。 |

数据集按内容版本保存：相同 `source_hash` 复用已有 `dataset_id`；同一日期和商品对的内容发生变化时创建新数据集，不覆盖此前版本。

`payload_json` 结构见 [normalized-data.md](normalized-data.md)，包含：

- 本品 SPU 下全部 SKU 的五字段映射。
- 本品 SKU 日记录及 SPU 汇总真实值。
- 五张竞品来源的标准化记录。
- 来源级和整体数据质量。

索引：

```sql
CREATE UNIQUE INDEX idx_analysis_datasets_source_hash
ON analysis_datasets(source_hash);

CREATE INDEX idx_analysis_datasets_pair_date
ON analysis_datasets(report_date, self_spu, competitor_spu, created_at);
```

## `analysis_tasks`

保存 Backend 调用 DeepSeek 的执行状态、输入和原始结果。AI 只读取后端已经计算完成的结构化事实。

| 字段 | SQLite 类型 | 约束 | 用途 |
|---|---|---|---|
| `analysis_id` | TEXT | PRIMARY KEY | AI 执行记录 UUID。 |
| `report_id` | TEXT | NOT NULL, FOREIGN KEY | 任务最终更新的唯一报告。 |
| `dataset_id` | TEXT | NOT NULL, FOREIGN KEY | 任务所属标准化数据集。 |
| `source_hash` | TEXT | NOT NULL | AI 输入内容版本哈希，用于判断当前任务是否需要替换。 |
| `payload_json` | TEXT | NOT NULL | 交给 AI 的确定性分析事实和风险说明。 |
| `result_json` | TEXT | NULL | AI 回传的总结、发现和建议。 |
| `model` | TEXT | NOT NULL | 本次执行使用的模型标识。 |
| `status` | TEXT | NOT NULL | `processing`、`completed`、`failed` 或 `expired`。 |
| `attempt_count` | INTEGER | NOT NULL, DEFAULT 0 | 后端执行该输入的次数。 |
| `error_message` | TEXT | NULL | 最近一次 AI 分析失败原因。 |
| `created_at` | TEXT | NOT NULL | 任务创建时间。 |
| `updated_at` | TEXT | NOT NULL | 最近状态更新时间。 |
| `completed_at` | TEXT | NULL | AI 分析完成时间。 |

`source_hash` 根据 AI 实际输入计算。已完成且输入不变时直接复用结果；失败或中断的相同输入在下次运行时重试；输入发生变化时，当前记录标记为 `expired`，然后创建新的 `processing` 记录。历史记录继续保留，但同一 `report_id` 只能有一条非 `expired` 记录。

索引：

```sql
CREATE INDEX idx_analysis_tasks_status_created
ON analysis_tasks(status, created_at);

CREATE INDEX idx_analysis_tasks_dataset
ON analysis_tasks(dataset_id, created_at);

CREATE INDEX idx_analysis_tasks_report_created
ON analysis_tasks(report_id, created_at);

CREATE UNIQUE INDEX idx_analysis_tasks_current_report
ON analysis_tasks(report_id) WHERE status <> 'expired';
```

## `reports`

保存可由 Web 直接读取的完整看板报告。同一业务日期、本品 SPU 和竞品 SPU 始终只有一份报告。

| 字段 | SQLite 类型 | 约束 | 用途 |
|---|---|---|---|
| `report_id` | TEXT | PRIMARY KEY | 报告 UUID。 |
| `dataset_id` | TEXT | NOT NULL, UNIQUE, FOREIGN KEY | 报告当前使用的标准化数据集。 |
| `report_date` | TEXT | NOT NULL | 报告业务日期。 |
| `self_spu` | TEXT | NOT NULL | 本品 SPU。 |
| `competitor_spu` | TEXT | NOT NULL | 竞品 SPU。 |
| `status` | TEXT | NOT NULL | `pending_ai`、`ready` 或 `ai_failed`。 |
| `report_json` | TEXT | NOT NULL | 后端确定性计算结果与 AI 结果合并后的完整看板 JSON。 |
| `created_at` | TEXT | NOT NULL | 报告创建时间。 |
| `updated_at` | TEXT | NOT NULL | 基础报告或 AI 结果更新时间。 |

状态含义：

| 状态 | 含义 |
|---|---|
| `pending_ai` | 后端确定性报告已生成，正在等待 DeepSeek 分析。 |
| `ready` | AI 已回传，报告包含完整总结和建议。 |
| `ai_failed` | AI 分析失败，基础数值报告仍可读取。 |

索引：

```sql
CREATE UNIQUE INDEX idx_reports_business_key
ON reports(report_date, self_spu, competitor_spu);

CREATE INDEX idx_reports_status_updated
ON reports(status, updated_at);
```

## 建表 SQL

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS analysis_datasets (
    dataset_id TEXT PRIMARY KEY,
    report_date TEXT NOT NULL,
    self_spu TEXT NOT NULL,
    competitor_spu TEXT NOT NULL,
    compare_number TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL UNIQUE REFERENCES analysis_datasets(dataset_id) ON DELETE CASCADE,
    report_date TEXT NOT NULL,
    self_spu TEXT NOT NULL,
    competitor_spu TEXT NOT NULL,
    status TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_tasks (
    analysis_id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    dataset_id TEXT NOT NULL REFERENCES analysis_datasets(dataset_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
```

## 写入流程

```text
读取 StarRocks 和飞书
  → 生成完整标准化日数据
  → 计算 source_hash
  → 写入或复用 analysis_datasets
  → 执行后端确定性计算
  → 按日期和商品对写入或更新唯一 reports，状态 pending_ai
  → AI 输入不变且已完成时复用当前结果
  → AI 输入变化时将旧记录标记 expired 并创建 processing 记录
  → Backend 直接调用 DeepSeek
  → 保存 analysis_tasks.result_json
  → 合并更新 reports，状态 ready
```

`quality_status=invalid` 的数据集允许保存以便排查，但不创建正式报告和 AI 执行记录。`quality_status=partial` 的数据集可以继续处理。部分字段未披露时保留 `masked/null` 事实；只有整块来源不可用时，才把缺失模块和对应风险写入 AI 输入事实与报告。

## MVP 不建立的表

- SPU/SKU 映射表：实时读取飞书，读取快照保存在数据集 JSON。
- 本品/竞品商品对表：实时读取飞书，以数仓核心指标表为有效性依据。
- 关键词、画像、流量和推广明细表：保存在数据集 JSON。
- 独立 AI 结果表：AI 原始结果保存在 `analysis_tasks.result_json`。
- 运行批次、调度记录、算法版本和迁移记录表：完整链路跑通后再评估。
