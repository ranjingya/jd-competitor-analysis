# 标准化事实数据

## 定位

`normalized_data.json` 是单个商品对、单个粒度、单个周期的事实快照。它保存任务参数、输入文件定位结果和从工作簿选出的原始业务行，不保存准真实估算值、差距判断、AI 建议或页面配置。

本文档是 Excel 字段映射和标准化 JSON 契约的唯一规范。原始数据的目录、文件格式、数据角色和周期规则见 [input-contract.md](input-contract.md)，估算规则见 [estimation.md](estimation.md)，最终分析结构见 [analysis-result.md](analysis-result.md)。

## 导航

- [输入参数](#输入参数)
- [输入来源](#输入来源)
- [顶层结构](#顶层结构)
- [业务行映射](#业务行映射)
- [数据约束](#数据约束)

## 输入参数

| 参数 | 标准化字段 | 说明 |
|---|---|---|
| 分析周期 | `meta.period` | 页面展示周期。 |
| 周期开始日期 | `meta.period_start` | `YYYY-MM-DD`。 |
| 周期结束日期 | `meta.period_end` | `YYYY-MM-DD`。 |
| 周期唯一键 | `meta.period_key` | 粒度与起止日期组成的唯一键。 |
| 输入周期目录 | `meta.period_file` | 当前周期输入目录名。 |
| 分析粒度 | `meta.granularity` | `day`、`week` 或 `month`。 |
| 本品 SPU | `meta.self_spu` | 本品真实数据唯一匹配条件。 |
| 竞品 SPU | `meta.competitor_spu` | 关键词等明细中的竞品筛选条件。 |
| 竞品字段前缀 | `meta.competitor_prefix` | 竞品对比表中的目标列名前缀。 |

## 输入来源

每份标准化事实数据只接收 [input-contract.md](input-contract.md) 确认后的一个商品对、一个粒度和一个周期。输入文件的读取状态记录到 `source_files[]`，角色冲突和数据缺口记录到 `warnings`。

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
| `period_start` | string | 周期开始日期。 |
| `period_end` | string | 周期结束日期。 |
| `period_key` | string | 例如 `week:2026-06-01_2026-06-07`。 |
| `period_file` | string | 当前周期输入目录名。 |
| `granularity` | string | `day`、`week` 或 `month`。 |
| `self_spu` | string | 本品 SPU。 |
| `competitor_spu` | string | 竞品 SPU。 |
| `competitor_prefix` | string | 竞品对比表中的字段前缀。 |
| `title` | string | 分析结果使用的报告标题。 |
| `generated_at` | string | ISO 8601 生成时间。 |

## `source_files[]`

每项至少包含：

| 字段 | 说明 |
|---|---|
| `role` | `self_real`、`core`、`traffic`、`keywords`、`customer_profile` 或 `promotion`。 |
| `label` | 数据角色中文名称。 |
| `file_name` | 输入文件名；ZIP 内工作簿使用 `压缩包.zip!工作簿.xlsx`。 |
| `sheet_name` | 实际读取的工作表。 |
| `required_level` | `core`、`complete` 或 `enhancement`。 |
| `status` | `ready`、`missing` 或 `conflict`。 |
| `warnings` | 当前输入的读取和匹配警告。 |

## 业务行映射

`core_raw`、`self_real` 和四类明细数组保留源表表头和值，并增加 `_row_index` 记录 Excel 行号。字段识别依赖表头名称，不依赖固定列号或固定工作表名。

### 本品真实值

| Excel 字段 | 用途 |
|---|---|
| `商品名称` | 本品名称。 |
| `SPU` | 筛选唯一 `self_real` 行。 |
| `浏览量`、`访客数`、`加购人数` | 核心规模指标与本品区间校验。 |
| `成交人数`、`成交转化率` | 成交公式、画像人数和区间校验。 |
| `成交单量`、`成交商品件数` | 件单关系与本品区间校验。 |
| `成交金额`、`成交客单价` | 成交公式、覆盖率分母和区间校验。 |

### 竞品核心区间

核心列使用 `本品{指标}` 与 `{competitor_prefix}{指标}` 模式匹配。支持成交金额、成交商品件数、成交单量、浏览量、访客数、加购人数、成交转化率和成交客单价；搜索点击次数作为可选审计指标保留。

### 明细数据

| 标准化数据 | 关键源字段 |
|---|---|
| `traffic_rows[]` | `时间`、三级渠道、两侧访客数及占比、成交金额、成交转化率、成交客户数。 |
| `keyword_rows[]` | `日期`、`关键词`、`SPUID`、`商品名称`、访客数、成交金额。 |
| `customer_profile_rows[]` | `时间`、`画像类型`、两侧成交客户数占比。 |
| `promotion_rows[]` | 两侧全站和非全站广告点击、交易额或广告订单金额。 |

## 数据约束

1. 原始 ZIP、XLSX 和工作表全程只读。
2. Excel 时间字段、`meta.period` 和 `meta.granularity` 必须一致。
3. 日维度起止日期相同；周和月使用源文件实际起止日期，不从日数据聚合。
4. `core_raw` 和 `self_real` 在正式分析中必须唯一。
5. `-`、空值和无法解析值原样保留，不转换成 `0`。
6. SPU、周期或文件角色无法唯一匹配时写入 `warnings`；核心数据冲突时停止正式分析。
7. 区间解析、P 候选、约束校正和业务判断全部留到分析阶段。
8. 分析规则调整后，允许使用同一份标准化事实数据重新生成分析结果。
