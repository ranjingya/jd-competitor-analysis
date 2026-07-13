# 字段映射

## 定位

本文档定义两段转换：原始 Excel 到 `normalized_data.json`，以及 `normalized_data.json` 到 `analysis_result.json`。两个 JSON 的结构分别以 [normalized-data.md](normalized-data.md) 和 [analysis-result.md](analysis-result.md) 为准；估算公式以 [estimation.md](estimation.md) 为准。

## 任务参数

| 参数 | 标准化字段 | 分析字段 |
|---|---|---|
| 分析周期 | `meta.period` | `meta.period`、明细行 `period` |
| 周期开始日期 | `meta.period_start` | `meta.period_start` |
| 周期结束日期 | `meta.period_end` | `meta.period_end` |
| 周期唯一键 | `meta.period_key` | `meta.period_key` |
| 文件周期片段 | `meta.period_file` | 不进入展示结果 |
| 分析粒度 | `meta.granularity` | `meta.granularity` |
| 本品 SPU | `meta.self_spu` | `meta.self_spu` |
| 竞品 SPU | `meta.competitor_spu` | `meta.competitor_spu` |
| 竞品字段前缀 | `meta.competitor_prefix` | 用于转换，不直接展示 |
| 看板标题 | 不进入标准化数据 | `meta.title` |

## Excel 到标准化数据

| 数据角色 | 表头确认字段 | 标准化目标 |
|---|---|---|
| 本品真实 SPU 数据 | `时间`、`SPU`、`访客数`、`成交金额` | `self_real` |
| 竞品核心数据对比 | `时间`、`本品访客数`、`{competitor_prefix}访客数` | `core_raw` |
| 流量来源对比 | `一级渠道`、`本品访客数`、`{competitor_prefix}访客数` | `traffic_rows[]` |
| 引流关键词对比 | `日期`、`关键词`、`SPUID` | `keyword_rows[]` |
| 成交客户画像对比 | `画像类型`、`本品成交客户数占比` | `customer_profile_rows[]` |
| 推广数据对比 | 本品与竞品广告点击或广告订单金额字段 | `promotion_rows[]` |

文件定位结果统一写入 `source_files[]`。每条业务行保留源表字段，并使用 `_row_index` 记录 Excel 行号。

周期以当前粒度目录中的“竞品数据对比”文件为锚点，从文件名提取起止日期。同一周期的六类文件必须拥有相同起止日期；日、周、月目录分别扫描，不跨粒度归并或换算。

### 本品真实值

| Excel 字段 | 分析用途 |
|---|---|
| `商品名称` | `meta.self_name` |
| `SPU` | 筛选 `self_real` 唯一行 |
| `浏览量` | 本品核心指标与区间校验 |
| `访客数` | 本品核心指标、关键词访客覆盖率分母 |
| `成交人数` | 成交公式、画像人数审计值 |
| `成交转化率` | 本品核心指标与区间校验 |
| `成交单量` | 本品校验 |
| `成交商品件数` | 本品校验 |
| `成交金额` | 本品核心指标、关键词成交覆盖率分母 |
| `成交客单价` | 本品核心指标与区间校验 |
| `加购人数` | 本品校验 |

### 竞品核心区间

核心字段使用以下模式匹配：

```text
本品{指标}
{competitor_prefix}{指标}
```

支持的指标包括成交金额、成交商品件数、成交单量、浏览量、访客数、加购人数、成交转化率、成交客单价；搜索点击次数作为可选审计指标保留。

### 明细数据

| 标准化数据 | 关键源字段 |
|---|---|
| `traffic_rows[]` | `时间`、三级渠道、两侧访客数及占比、成交金额、成交转化率、成交客户数 |
| `keyword_rows[]` | `日期`、`关键词`、`SPUID`、`商品名称`、`访客数`、`成交金额` |
| `customer_profile_rows[]` | `时间`、`画像类型`、两侧成交客户数占比 |
| `promotion_rows[]` | 两侧全站和非全站广告点击、交易额或广告订单金额 |

## 标准化数据到分析结果

### 元信息和审计

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `meta.period`、`meta.granularity` | `meta` | 直接复制。 |
| `meta.self_name` | `self_real.商品名称` | 清洗文本。 |
| `meta.competitor_name` | `keyword_rows[].商品名称` | 按竞品 SPU 筛选并唯一化。 |
| `source_files[]` | `source_files[]` | 保留角色、文件、工作表、状态和警告。 |
| `self_validation[]` | `self_real`、`core_raw` | 本品真实值与本品区间逐指标校验并计算 P。 |
| `competitor_core_conversions[]` | `core_raw`、`traffic_rows[]` | 解析竞品区间，生成候选值，并用成交公式和顶层流量约束校正。 |
| `risks[]` | `warnings`、转换检查 | 汇总缺失、冲突、降级和口径风险。 |

### 核心对比

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `comparison[]` | `self_validation[]`、`competitor_core_conversions[]` | 按指标计算绝对差、百分点差、倍率和领先状态。 |
| `core_metrics[]` | `comparison[]` | 选择成交金额、访客数、成交转化率和成交客单价。 |
| `meta.summary` | `core_metrics[]` | 汇总主要优势。 |
| `meta.weakness_summary` | `core_metrics[]` | 汇总主要短板。 |

比例指标使用百分点差；规模和金额指标使用原单位绝对差，并计算领先方相对落后方的倍率。

### 流量来源

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `traffic_sources[].path` | 三级渠道字段 | 过滤空层级后使用 ` > ` 拼接。 |
| 两侧访客、成交和转化字段 | 对应渠道区间与占比 | 按 [estimation.md](estimation.md) 的父子渠道约束估算。 |
| `traffic_sources[].self_current_level_visitor_rate`、`competitor_current_level_visitor_rate` | 两侧访客估算值、渠道层级 | 以同一父渠道下的兄弟节点访客合计为分母计算同层访客占比。 |
| `traffic_sources[].self_total_visitor_rate`、`competitor_total_visitor_rate` | 两侧源表访客占比、一级渠道访客合计 | 优先使用源表披露占比；缺失时以一级渠道访客合计为分母回算。 |
| `traffic_sources[].gap_tags` | 两侧最终值 | 生成访客、成交和转化差距标签。 |
| `traffic_sources[].suggested_action` | 差距组合 | 根据流量规模和承接效率生成动作方向。 |

### 关键词

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `keywords.rows[]` | `keyword_rows[]` | 按 SPU 拆分后，以关键词做全外连接。 |
| `coverage_relation` | 两侧关键词集合 | 标记共同词、本品独有词或竞品独有词。 |
| 两侧访客和成交金额 | 对应区间 | 使用区间中位数估算。 |
| `keywords.summary` | 完整关键词集合 | 统计共同词和两侧独有词数量。 |
| `keywords.coverage` | 关键词估算合计、核心指标 | 计算访客和成交金额覆盖率。 |

### 客户画像

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `customer_profile.dimensions[]` | `customer_profile_rows[]` | 识别性别、年龄、省份、城市标题及其明细。 |
| `items[].gap_rate` | 两侧占比 | `self_rate - competitor_rate`。 |
| 两侧画像人数 | 占比、两侧成交人数 | 占比乘对应成交人数，仅作为审计值。 |
| `items[].judgement` | `gap_rate` | 大于等于 `1pct` 为本品领先，小于等于 `-1pct` 为本品落后。 |

### 推广、Tab 和诊断

| 分析字段 | 标准化来源 | 转换规则 |
|---|---|---|
| `promotion` | `promotion_rows[]` | 估算广告点击和归因成交，计算归因成交占比。 |
| `tabs[id=traffic]` | `traffic_sources[]` | 差异大的 3 至 5 项进入 `highlights`，完整数据进入 `rows`。 |
| `tabs[id=keywords]` | `keywords` | 重点关键词进入 `highlights`，全部关键词进入 `rows`。 |
| `tabs[id=customer_profile]` | `customer_profile` | 重点画像进入 `highlights`，完整画像进入 `rows`。 |
| `diagnosis[]` | 核心对比和可用明细模块 | 分开生成事实证据与建议动作。 |

## 缺失处理

1. `-`、空值和不可解析内容按缺失处理，不转成 `0`。
2. 核心必需数据缺失时停止正式分析。
3. 关键词或画像缺失时保留对应结构，使用空数组并写入 `risks[]`。
4. 推广数据缺失时将 `promotion.available` 设为 `false`，不生成投放判断。
5. HTML 展示字段不得使用示例值补齐。
