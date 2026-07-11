# 分析结果

## 定位

`analysis_result.json` 保存按当前估算逻辑生成的准真实值、差距、建议和风险，是 HTML 看板与人工复核共同使用的数据契约。本文档是该 JSON 的结构与字段约束规范；字段来源见 [field-map.md](field-map.md)，计算规则见 [estimation.md](estimation.md)，页面消费规则见 [dashboard.md](dashboard.md)。

可执行样例位于 `assets/examples/analysis-result.example.json`；不含业务值的空结构位于 `assets/analysis-result.template.json`。空结构用于初始化和联调，本文档负责字段语义与约束。

## 顶层结构

| 字段 | 类型 | 要求 | 说明 |
|---|---|---|---|
| `schema_version` | string | 必须 | 当前结构版本。 |
| `meta` | object | 必须 | 周期、粒度、分析对象、置信度和首屏判断。 |
| `source_files` | array | 必须 | 输入文件、工作表、状态和读取风险。 |
| `self_validation` | array | 必须 | 本品真实值落区间校验和本品 P。 |
| `competitor_core_conversions` | array | 必须 | 竞品候选值、最终值、转换依据和约束检查。 |
| `core_metrics` | array | 必须 | 首屏核心指标卡数据。 |
| `comparison` | array | 必须 | 本品与竞品的完整核心指标对比。 |
| `traffic_sources` | array | 必须 | 完整渠道层级、流量、成交和差距。 |
| `keywords` | object | 完整看板必需 | 关键词覆盖统计和完整关键词行。 |
| `customer_profile` | object | 完整看板必需 | 性别、年龄、省份、城市画像对比。 |
| `promotion` | object/null | 诊断增强 | 推广估算和广告归因判断。 |
| `tabs` | array | 必须 | HTML 差距来源 Tab 的直接渲染数据。 |
| `diagnosis` | array | 必须 | AI 核心判断、证据和建议。 |
| `action_tracking` | array | 可选 | 后续行动和复盘字段。 |
| `risks` | array | 必须 | 缺失、冲突、降级和口径风险。 |

顶层字段保持稳定。数据不足时保留对应字段，使用空数组、空对象或 `null` 表达，并在 `risks[]` 记录原因。

## 周期字段

`meta` 必须包含 `period`、`period_start`、`period_end`、`period_key` 和 `granularity`。`period_key` 在同一商品对的报告索引中唯一，用于目录定位、前端选择和报告缓存。日、周、月报告分别读取对应粒度源表并独立计算。

## 核心审计结构

### `self_validation[]`

每行至少包含：

- `metric_id`
- `metric_label`
- `actual_value`
- `range_text`
- `range_low`
- `range_high`
- `position_p`
- `in_range`
- `median_error_rate`
- `historical_p`
- `historical_p_period`
- `historical_p_error_rate`
- `note`

没有可用历史 P 时，历史 P 相关字段为 `null`。

### `competitor_core_conversions[]`

每行至少包含：

- `metric_id`
- `metric_label`
- `range_text`
- `range_low`
- `range_high`
- `median_candidate`
- `p_candidate`
- `historical_p_candidate`
- `final_value`
- `basis`
- `confidence`
- `checks`

`checks` 记录原始区间、成交公式、顶层流量约束、父子渠道约束和调整结果。未使用的候选字段为 `null`。

## HTML 直接消费结构

### `core_metrics[]`

每行至少包含 `id`、`label`、`unit`、`self_value`、`competitor_value`、`gap_abs_text`、`ratio_text`、`gap_text`、`status` 和 `priority`。

### `tabs[]`

每个 Tab 至少包含 `id`、`label`、`headline`、`highlights`、`columns`、`rows` 和 `notes`。客户画像 Tab 同时包含 `dimension_field` 和 `dimension_label`。

### `diagnosis[]`

每项至少包含 `title`、`evidence`、`recommendation`、`status` 和 `source`。证据和建议分开保存，禁止把建议拼进证据字段。

## 审计约定

1. 关键结果保留 `source`、`basis` 或 `method`、`confidence`、`checks` 或 `warnings`。
2. 本品值始终标记为真实值，竞品值始终标记为准真实估算值。
3. 比例指标保存百分点差，规模和金额指标保存原单位绝对差及领先方倍率。
4. HTML 只读取本文件，不执行区间解析、候选选择和公式校正。
5. 模块降级时保留结构并写入 `risks[]`，不得用示例数据补齐。
