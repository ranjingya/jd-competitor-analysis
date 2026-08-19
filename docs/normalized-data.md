# 数仓日数据标准化契约

## 定位

标准化数据是一组本品 SPU、竞品 SPU 和业务日期对应的事实快照。它保留数仓原始区间、解析后的上下界、来源批次和质量状态，不保存区间中位值、P 候选、准真实估算值、差距判断或 AI 建议。

竞品数据来自以下五张 StarRocks 日表：

| `source_id` | 数仓表 |
|---|---|
| `core_metrics` | `ods_rpa_jdzy_competitor_data_compare_f` |
| `traffic_sources` | `ods_rpa_jdzy_traffic_source_compare_f` |
| `traffic_keywords` | `ods_rpa_jdzy_traffic_keyword_compare_f` |
| `customer_profiles` | `ods_rpa_jdzy_deal_customer_compare_f` |
| `promotion` | `ods_rpa_jdzy_promotion_data_compare_f` |

## 顶层结构

```json
{
  "schema_version": "2.0",
  "report_date": "2026-08-11",
  "pair": {
    "compare_number": "100174558585+100112260075",
    "self_spu": "100174558585",
    "competitor_spu": "100112260075"
  },
  "sources": {
    "core_metrics": {},
    "traffic_sources": {},
    "traffic_keywords": {},
    "customer_profiles": {},
    "promotion": {}
  },
  "quality": {
    "status": "partial",
    "issues": []
  }
}
```

一份数据只对应一个自然日和一个商品对。`compare_number` 固定使用 `<本品SPU>+<竞品SPU>`。

## 来源公共结构

五个来源使用同一个外层：

```json
{
  "source": {
    "table": "ods_rpa_jdzy_competitor_data_compare_f",
    "updated_at": "2026-08-12 03:00:00",
    "row_ids": [1],
    "row_count": 1
  },
  "records": [],
  "quality": {
    "status": "ready",
    "issues": []
  }
}
```

同一商品对、同一天存在多次同步时，只读取 `updated_at` 最新的批次。批次内部按原始 `id` 升序排列，供画像标题与明细恢复原始顺序。

来源质量状态：

| 状态 | 含义 |
|---|---|
| `ready` | 记录及指标完整。 |
| `partial` | 至少存在一个可用指标，但部分指标未披露、解析失败或存在结构问题。 |
| `unavailable` | 没有记录，或全部指标均不可用。 |

整体质量状态：

| 状态 | 含义 |
|---|---|
| `ready` | 五个来源全部完整。 |
| `partial` | 核心指标可用，至少一个其他来源不完整。 |
| `invalid` | 核心指标不可用，不能继续生成正式估算结果。 |

## 指标公共结构

所有竞品脱敏值固定包含以下字段：

```json
{
  "raw": "￥1,000 ~ ￥2,000",
  "status": "range",
  "low": 1000,
  "high": 2000,
  "unit": "currency"
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `raw` | 数仓原始值；源字段不存在时为 `null`，源值为横线时为 `-`。 |
| `status` | `range`、`exact`、`masked` 或 `invalid`。 |
| `low` | 可用值的下界。 |
| `high` | 可用值的上界；单值与 `low` 相同。 |
| `unit` | `count`、`currency` 或 `ratio`。 |

固定字段不存在、空值和源值 `-` 均使用 `masked`，并将 `low`、`high` 设为 `null`。存在但无法解析的内容使用 `invalid`。标准化阶段不生成 `mid`。

## 核心指标

每条 `core_metrics.records[]` 固定包含 `self` 和 `competitor`，两侧字段一致：

```json
{
  "self": {
    "page_views": {},
    "visitors": {},
    "add_to_cart_users": {},
    "orders": {},
    "units_sold": {},
    "gmv": {},
    "conversion_rate": {},
    "average_order_value": {},
    "search_clicks": {}
  },
  "competitor": {
    "page_views": {},
    "visitors": {},
    "add_to_cart_users": {},
    "orders": {},
    "units_sold": {},
    "gmv": {},
    "conversion_rate": {},
    "average_order_value": {},
    "search_clicks": {}
  }
}
```

本品读取源字段 `本品{指标}`，竞品读取 `竞品1{指标}`。当前商品对中的竞品 SPU 对应 `竞品1`。

## 流量来源

每条 `traffic_sources.records[]` 包含：

```json
{
  "channel_level_1": "站内场域",
  "channel_level_2": "搜索",
  "channel_level_3": null,
  "channel_path": "站内场域 > 搜索",
  "self": {
    "visitors": {},
    "visitor_share": {},
    "gmv": {},
    "conversion_rate": {},
    "buyers": {}
  },
  "competitor": {
    "visitors": {},
    "visitor_share": {},
    "gmv": {},
    "conversion_rate": {},
    "buyers": {}
  }
}
```

渠道层级为空或 `-` 时转换为 `null`。`channel_path` 只连接有效层级。

## 引流关键词

每条 `traffic_keywords.records[]` 包含：

```json
{
  "product_role": "self",
  "spu_id": "100174558585",
  "product_name": "商品名称",
  "keyword": "雨衣",
  "visitors": {},
  "gmv": {}
}
```

`product_role` 根据 `SPUID` 与当前商品对匹配为 `self` 或 `competitor`。商品对之外的 SPU 不进入标准化记录，并写入质量问题。

## 成交客户画像

每条 `customer_profiles.records[]` 包含：

```json
{
  "dimension": "age",
  "segment": "16-25岁",
  "self_share": {},
  "competitor_share": {}
}
```

画像维度映射：

| 源标题 | `dimension` |
|---|---|
| 性别 | `gender` |
| 年龄 | `age` |
| 地区 | `region` |
| 省份 | `province` |
| 城市 | `city` |

标题行用于确定后续明细所属维度，不进入 `records`。批次缺少标题行时，只对名称明确的年龄、性别、省份或城市项进行推断；无法判断时使用 `unknown` 并记录质量问题。缺少任一占比字段时固定补为 `masked`。

## 推广数据

每条 `promotion.records[]` 包含：

```json
{
  "self": {
    "full_site": {
      "gmv": {},
      "core_position_clicks": {}
    },
    "non_full_site": {
      "ad_clicks": {},
      "ad_order_gmv": {}
    }
  },
  "competitor": {
    "full_site": {
      "gmv": {},
      "core_position_clicks": {}
    },
    "non_full_site": {
      "ad_clicks": {},
      "ad_order_gmv": {}
    }
  }
}
```

本品读取 `本店商品` 字段，竞品读取 `竞品1` 字段。全站与非全站口径分别保存，不在标准化阶段合并。

## 数据约束

1. 数仓和飞书来源全程只读。
2. 标准化记录必须固定输出约定字段，缺失字段统一补为 `masked`。
3. `masked` 不等于数值 `0`，不参与后续确定性计算。
4. `raw` 保留来源表达，供数据问题审计。
5. 标准化阶段只解析事实，不生成中位值、估算值、结论或建议。
6. 算法规则调整后，可以使用同一份标准化事实重新计算报告。
