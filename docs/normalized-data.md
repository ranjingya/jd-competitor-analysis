# 数仓日数据标准化契约

## 定位

标准化数据是一组本品 SPU、竞品 SPU 和业务日期对应的事实快照。它保存本品 SKU 构成和 SPU 汇总真实值，并保留竞品数仓原始区间、解析后的上下界、来源批次和质量状态；不保存区间中位值、P 候选、准真实估算值、差距判断或 AI 建议。

本品数据来自飞书 SPU/SKU 映射和 StarRocks 日表 `ods_rpa_jd_jd_business_product_detail_f`。飞书映射固定保留 SPU ID、SKU ID、69 码、商品名和规格。

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
    "self_spu": "100174558585",
    "competitor_spu": "100112260075"
  },
  "self_product": {},
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

一份数据只对应一个自然日和一个商品对，本品与竞品 SPU 使用两个独立字段保存。

## 本品 SKU 与 SPU

`self_product` 使用以下固定结构：

```json
{
  "spu_id": "100174558585",
  "source": {
    "mapping": "lark_base",
    "daily_table": "ods_rpa_jd_jd_business_product_detail_f",
    "report_date": "2026-08-11"
  },
  "sku_components": [
    {
      "spu_id": "100174558585",
      "sku_id": "10001",
      "barcode_69": "69001",
      "product_name": "商品名称",
      "specification": "黄色 M"
    }
  ],
  "sku_daily_records": [
    {
      "sku_id": "10001",
      "data_status": "ready",
      "metrics": {
        "page_views": 100,
        "visitors": 50,
        "buyers": 10,
        "orders": 9,
        "units_sold": 11,
        "gmv": 1000,
        "add_to_cart_users": 12,
        "conversion_rate": 0.2,
        "average_order_value": 100,
        "search_clicks": null
      }
    }
  ],
  "spu_daily_metrics": {
    "page_views": 100,
    "visitors": 50,
    "buyers": 10,
    "orders": 9,
    "units_sold": 11,
    "gmv": 1000,
    "add_to_cart_users": 12,
    "conversion_rate": 0.2,
    "average_order_value": 100,
    "search_clicks": null
  },
  "quality": {
    "status": "ready",
    "mapped_sku_count": 1,
    "warehouse_sku_count": 1,
    "ready_sku_count": 1,
    "missing_sku_ids": [],
    "partial_sku_ids": [],
    "issues": []
  }
}
```

`sku_components` 始终保留飞书映射中的全部 SKU。某个 SKU 没有当天数仓记录时，仍输出对应 `sku_daily_records`，将 `data_status` 设为 `missing`，所有指标设为 `null`，并把 SKU ID 写入 `missing_sku_ids`。

本品汇总规则：

| SPU 指标 | SKU 来源或公式 |
|---|---|
| `page_views` | `pv` 相加。 |
| `visitors` | `uv` 相加。 |
| `buyers` | `transaction_user` 相加。 |
| `orders` | `transaction_order` 相加。 |
| `units_sold` | `transaction_product` 相加。 |
| `gmv` | `transaction_amount` 相加。 |
| `add_to_cart_users` | `cart_user` 相加。 |
| `conversion_rate` | 汇总 `buyers / visitors`。 |
| `average_order_value` | 汇总 `gmv / buyers`。 |
| `search_clicks` | 本品日表不提供，固定为 `null`。 |

本品质量状态：

| 状态 | 含义 |
|---|---|
| `ready` | 每个映射 SKU 都有完整的当天加总字段。 |
| `partial` | 至少一个 SKU 可用，但有映射 SKU 缺数或加总字段不完整。 |
| `unavailable` | 没有 SKU 映射，或全部映射 SKU 都没有当天记录。 |

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
| `partial` | 至少一个来源或本品 SKU 数据缺失、未披露或存在结构问题，现有事实仍可生成报告。 |
| `invalid` | 数据集契约无效，不能进入报告流程；普通业务数据缺失不属于该状态。 |

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
5. 本品实际数值缺失时使用 `null`；竞品区间字段缺失时使用固定指标对象并标记 `masked`。
6. 本品映射不完整时保留可用 SKU 的部分汇总，但整体质量不得标记为 `ready`。
7. 标准化阶段只解析和汇总事实，不生成中位值、估算值、结论或建议。
8. 算法规则调整后，可以使用同一份标准化事实重新计算报告。
