# 分析结果

## 定位

`analysis_result.json` 保存当前周期的准真实估算值、差距、审计信息、AI 建议和风险，是 Vite 看板与人工复核共同使用的最终数据契约。

本文档是标准化事实到分析结果的字段映射和最终 JSON 结构的唯一规范。输入事实见 [normalized-data.md](normalized-data.md)，计算规则见 [estimation.md](estimation.md)，AI 建议规则见 [ai-recommendations.md](ai-recommendations.md)，页面消费规则见 [dashboard.md](dashboard.md)。

可执行样例位于 `assets/analysis-result.example.json`；空结构位于 `assets/analysis-result.template.json`。

## 导航

- [顶层结构](#顶层结构)
- [元信息与审计映射](#元信息与审计映射)
- [核心审计结构](#核心审计结构)
- [分析模块映射](#分析模块映射)
- [AI 建议](#ai_recommendations)
- [缺失与审计约定](#缺失与审计约定)

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
| `promotion` | object | 必须 | 推广模块稳定容器；缺失时以 `available=false` 表示。 |
| `tabs` | array | 必须 | 三个差距来源 Tab 的直接渲染数据。 |
| `ai_recommendations` | array | 必须 | Skill 生成的结构化 AI 建议；基础分析阶段为空数组。 |
| `risks` | array | 必须 | 缺失、冲突、降级和口径风险。 |

顶层字段保持稳定。数据不足时保留对应字段，使用空数组、空对象或字段内 `null` 表达，并在 `risks[]` 记录原因。

## 元信息与审计映射

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `meta.period`、起止日期、周期键、粒度 | `meta` | 直接复制。 |
| `meta.self_spu`、`meta.competitor_spu` | `meta` | 直接复制。 |
| `meta.self_name` | `self_real.商品名称` | 清洗文本。 |
| `meta.competitor_name` | `keyword_rows[].商品名称` | 按竞品 SPU 筛选并唯一化。 |
| `meta.title` | 任务参数 | 使用调用方标题。 |
| `meta.confidence` | 本品校验与竞品约束检查 | 按 [estimation.md](estimation.md) 综合判断。 |
| `meta.summary`、`meta.weakness_summary` | `core_metrics[]` | 汇总主要优势和短板，不生成行动建议。 |
| `source_files[]` | `source_files[]` | 保留角色、文件、工作表、状态和警告。 |
| `risks[]` | `warnings`、转换检查 | 汇总缺失、冲突、降级和口径风险。 |

`meta` 必须包含 `period`、`period_start`、`period_end`、`period_key` 和 `granularity`。`period_key` 在同一商品对的报告索引中唯一。

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
- `position_p_valid`
- `in_range`
- `median_error_rate`
- `historical_p`
- `historical_p_period`
- `historical_p_periods`
- `historical_p_error_rate`
- `note`

本品最终值始终使用真实值。`position_p` 保存未经截断的原始位置，只有 `position_p_valid=true` 时才能参与当期竞品估算。没有可用历史 P 时，历史 P 数值为 `null`，来源周期数组为空。

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
- `historical_p`
- `historical_p_periods`
- `candidate_source`
- `selected_candidate`
- `final_value`
- `basis`
- `confidence`
- `checks`

`candidate_source` 取 `same_period_p`、`historical_p` 或 `median`，对应当期有效 P、同粒度历史有效 P 均值和中位值兜底。`checks` 记录原始区间、成交公式、顶层流量约束、件单关系、调整结果和无法消解的冲突；未生成的候选字段为 `null`。

## 分析模块映射

### 核心对比

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `comparison[]` | `self_validation[]`、`competitor_core_conversions[]` | 计算绝对差、百分点差、倍率和领先状态。 |
| `core_metrics[]` | `comparison[]` | 选择成交金额、访客数、成交转化率和成交客单价。 |

比例指标使用百分点差；规模和金额指标使用原单位绝对差，并计算领先方相对落后方的倍率。

### 流量来源

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `traffic_sources[].path` | 三级渠道字段 | 过滤空层级后使用 ` > ` 拼接。 |
| 两侧访客、成交和转化字段 | 对应渠道区间与占比 | 按父子渠道约束估算。 |
| 两侧 `current_level_visitor_rate` | 两侧访客估算值、渠道层级 | 以同一父渠道的兄弟节点访客合计为分母。 |
| 两侧 `total_visitor_rate` | 源表占比、一级渠道访客合计 | 优先使用披露占比；缺失时回算。 |
| `gap_tags`、`judgement` | 两侧最终值 | 保存差距标签和结构判断，不生成行动建议。 |

### 关键词

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `keywords.rows[]` | `keyword_rows[]` | 按 SPU 拆分后，以关键词做全外连接。 |
| `coverage_relation` | 两侧关键词集合 | 标记共同词、本品独有词或竞品独有词。 |
| 两侧访客和成交金额 | 对应区间 | 按估算规则计算。 |
| `keywords.summary` | 完整关键词集合 | 统计共同词和两侧独有词数量。 |
| `keywords.coverage` | 关键词估算合计、核心指标 | 计算访客和成交金额覆盖率。 |

### 客户画像

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `customer_profile.dimensions[]` | `customer_profile_rows[]` | 识别性别、年龄、省份、城市标题及明细。 |
| `items[].gap_rate` | 两侧占比 | `self_rate - competitor_rate`。 |
| 两侧画像人数 | 占比、两侧成交人数 | 占比乘对应成交人数，仅作为审计值。 |
| `items[].judgement` | `gap_rate` | 使用统一百分点阈值标记领先、落后或接近。 |

### 推广

`promotion` 始终是对象，至少包含：

```json
{
  "available": false,
  "self": {},
  "competitor": {},
  "attributed_gmv_rate": null,
  "judgement": null,
  "notes": []
}
```

有可用推广数据时填充两侧广告点击、广告归因成交和贡献比例。推广数据缺失时保持 `available=false`，不生成投放判断，并在 `risks[]` 说明。

### `tabs[]`

每个 Tab 至少包含 `id`、`label`、`headline`、`highlights`、`columns`、`rows` 和 `notes`。客户画像 Tab 同时包含 `dimension_field` 和 `dimension_label`。

`highlights` 只保存重点对象、实际值、差距和状态，不包含行动建议。完整行保留页面排序和人工复核需要的字段。

## `ai_recommendations[]`

基础分析流程只初始化空数组。Skill 读取完整分析结果和 [ai-recommendations.md](ai-recommendations.md) 后生成建议，再通过 `scripts/main.py apply-ai` 写回。独立建议 JSON 是位于 `scripts/output/` 之外的临时输入，写回确认后立即清理，不属于最终结果契约。

每项至少包含：

- `source_id`：`traffic`、`keywords` 或 `customer_profile`。
- `source_label`：页面展示的差距来源名称。
- `target`：建议针对的具体渠道、关键词或画像项。
- `status`：`warning`、`advantage` 或 `neutral`。
- `evidence`：直接引用本周期实际值、竞品准真实估算值和差距，不写动作。
- `actions`：1–3 条基于完整上下文独立判断的动作。
- `validation`：使用当前基线定义的验收条件。

网页只展示该数组，不根据数值、Tab 或固定句库生成建议。

## 缺失与审计约定

1. `-`、空值和不可解析内容按缺失处理，不转成 `0`。
2. 核心必需数据缺失或冲突时停止正式分析。
3. 关键词或画像缺失时保留对应对象和 Tab，使用空数组并写入 `risks[]`。
4. 本品值始终标记为真实值，竞品值始终标记为准真实估算值。
5. 关键结果保留 `source`、`basis` 或 `method`、`confidence`、`checks` 或 `warnings`。
6. 网页不执行区间解析、候选选择、公式校正或 AI 建议生成。
7. 不使用示例数据补齐缺失模块。
