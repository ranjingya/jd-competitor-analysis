# 标准化数据

## 定位

`normalized_data.json` 是单个分析周期的事实数据快照，保存任务参数、输入文件信息和从 Excel 选出的原始业务行。它不保存准真实值、差距判断、AI 建议或页面展示配置。

一份文件只对应一个商品对、一个粒度和一个周期。日、周、月数据分别生成，不在同一分析单元内混合。

## 顶层结构

| 字段 | 类型 | 要求 | 说明 |
|---|---|---|---|
| `schema_version` | string | 必须 | 数据结构版本。 |
| `meta` | object | 必须 | 分析对象、周期、粒度和生成信息。 |
| `source_files` | array | 必须 | 六类输入文件的定位与读取状态。 |
| `core_raw` | object | 必须 | 当前周期的竞品核心对比行。 |
| `self_real` | object | 必须 | 当前周期、本品 SPU 的唯一真实数据行。 |
| `traffic_rows` | array | 核心必需 | 当前周期的完整流量来源行。 |
| `keyword_rows` | array | 完整看板必需 | 当前周期的完整关键词行。 |
| `customer_profile_rows` | array | 完整看板必需 | 当前周期的完整成交客户画像行。 |
| `promotion_rows` | array | 诊断增强 | 当前周期的推广数据行。 |
| `warnings` | array | 必须 | 文件发现、读取、匹配和字段检查警告。 |

## `meta`

| 字段 | 类型 | 说明 |
|---|---|---|
| `period` | string | 展示周期，例如 `2026-06-01~2026-06-07`。 |
| `period_start` | string | 周期开始日期，格式为 `YYYY-MM-DD`。 |
| `period_end` | string | 周期结束日期，格式为 `YYYY-MM-DD`。 |
| `period_key` | string | 粒度与周期组成的唯一键，例如 `week:2026-06-01_2026-06-07`。 |
| `period_file` | string | 文件名使用的周期片段。 |
| `granularity` | string | `day`、`week` 或 `month`。 |
| `self_spu` | string | 本品 SPU。 |
| `competitor_spu` | string | 竞品 SPU。 |
| `competitor_prefix` | string | 竞品对比表中的字段前缀。 |
| `generated_at` | string | ISO 8601 生成时间。 |

## `source_files[]`

每项至少包含：

| 字段 | 说明 |
|---|---|
| `role` | `self_real`、`core`、`traffic`、`keywords`、`customer_profile` 或 `promotion`。 |
| `label` | 数据角色中文名称。 |
| `file_name` | 输入文件名。 |
| `sheet_name` | 实际读取的工作表。 |
| `required_level` | `core`、`full` 或 `enhancement`。 |
| `status` | `ready`、`missing` 或 `conflict`。 |
| `warnings` | 当前输入的读取和匹配警告。 |

## 业务行

`core_raw`、`self_real` 以及四类明细数组保留源表表头和值，并增加 `_row_index` 记录 Excel 行号。字段识别依赖表头名称，不依赖固定列号或固定工作表名。

| 数据块 | 唯一性或筛选规则 |
|---|---|
| `core_raw` | 当前周期竞品核心对比表的数据行；正式分析要求唯一。 |
| `self_real` | `SPU == meta.self_spu`；正式分析要求唯一。 |
| `traffic_rows` | 保留当前周期全部渠道层级行。 |
| `keyword_rows` | 保留当前周期本品与竞品全部披露关键词行。 |
| `customer_profile_rows` | 保留当前周期全部画像标题行和画像项。 |
| `promotion_rows` | 保留当前周期全部可用推广行。 |

## 数据约束

1. 原始 Excel 全程只读。
2. 文件名只用于生成候选集，最终数据角色必须通过表头确认。
3. Excel 时间字段、`meta.period` 和 `meta.granularity` 必须一致。
4. 日维度的起止日期相同；周和月使用对应目录中源文件的实际起止日期，不从日数据聚合。
5. `-`、空值和无法解析值原样保留，不转换成 `0`。
6. SPU、周期或文件角色无法唯一匹配时写入 `warnings`；核心数据冲突时停止正式分析。
7. 区间解析、候选值选择和业务判断在分析阶段完成，规则见 [estimation.md](estimation.md)。
8. 分析规则调整后，可使用同一份标准化数据重新生成 `analysis_result.json`。
