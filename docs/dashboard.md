# 网页看板

## 定位

网页看板位于 `web/`，只负责展示 Backend 返回的数据，不读取数仓、标准化中间数据或服务器文件，也不执行估算和 AI 分析。

## 本地启动

先在 `127.0.0.1:8000` 启动 Backend，再运行：

```bash
cd web
npm ci
npm run dev
```

Vite 把 `/api` 转发到本地 Backend。生产环境中，同一路径由 Nginx 转发到 `jd-competitor-analysis-backend:8000`。

## 加载流程

```text
打开网页
  → GET /api/product-pairs
  → 默认选择最新日报对应的商品对和 report_id
  → GET /api/reports/{report_id} 渲染当前完整报告
  → GET /api/reports/trends 加载最近七天四项核心指标
```

商品对接口返回日、周、月各粒度的最新报告和报告数量。最新报告条目的 `path` 由 Backend 生成，例如：

```json
{
  "period_key": "day:2026-08-18",
  "path": "/api/reports/报告ID"
}
```

条目使用 `start_date` 和 `end_date` 表示周期范围，并包含本品、竞品的 SPU 与商品名。Web 默认打开最新日报，报告选择和页面会话缓存均使用唯一的 `report_id`。

日期选择器展开、切换月份或年份时调用：

```text
GET /api/reports/periods?self_spu=...&competitor_spu=...&granularity=day&context=2026-08
```

接口只返回当前日历上下文的轻量报告条目和可导航上下文。选择具体日、周或月后，Web 再按 `report_id` 加载对应完整报告。趋势图调用 `/api/reports/trends`，响应仅包含周期元数据和成交金额、访客数、成交转化率、成交客单价，不读取五张分析表及 AI 内容。

报告也可按周期范围读取：

```text
GET /api/reports/{granularity}/{start_date}/{end_date}
```

日报的 `start_date` 与 `end_date` 相同；自然周的日期范围为周一至周日。本品 SPU 的 SKU 构成通过页面的“查看 SKU”入口展示，数据来自 `GET /api/reports/{report_id}/skus`。弹窗固定展示 `spu_id`、`sku_id`、`barcode_69`、`product_name` 和 `specification` 五个字段，并使用生成报告时的数据集快照。

## 展示约束

1. 本品值标记为真实值，竞品值标记为估算值。
2. 缺失值显示为 `-`，数值零正常显示。
3. 页面只展示 Backend 返回的 AI 结果，不拼接或回退到模板建议。
4. 缺失模块保持空状态，并展示对应风险说明。
5. 已加载报告可以在当前页面会话中按 `report_id` 缓存。
6. 商品对切换后，周期选择与趋势数据均限定在当前本品和竞品组合内。
7. 其他周期的完整报告只在用户选择对应周期后加载。
