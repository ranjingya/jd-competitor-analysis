# 网页看板

## 定位

网页看板由 Vite 提供本地访问入口。页面先读取轻量 `report-index.json`，再根据用户选择按需读取一份 `analysis_result.json`。网页不读取 Excel、`normalized_data.json`，也不执行准真实值估算。

## 运行目录

Vite 源码位于 `scripts/web/`，运行产物位于 `scripts/output/`。以上路径均相对于 Skill 根目录，输出目录保持在版本控制之外。

```text
scripts/output/
├── report-index.json
├── day/{period_file}/analysis_result.json
├── week/{period_file}/analysis_result.json
└── month/{period_file}/analysis_result.json
```

## 报告索引

`report-index.json` 至少包含：

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-06-29T10:00:00",
  "reports": {
    "day": [],
    "week": [],
    "month": []
  }
}
```

每个报告条目至少包含 `period`、`period_start`、`period_end`、`period_key`、`generated_at`、`confidence` 和 `path`。数组按开始日期和结束日期升序排列，最后一项是当前粒度的最新周期。

## 加载流程

```text
打开网页
  -> GET /reports/report-index.json
  -> 默认选择最新日报；没有日报时选择第一个有数据的粒度
  -> GET 当前条目的 path
  -> renderDashboard(analysis_result)
```

页面启动时只读取一次索引，不监控 Excel，也不定时刷新。业务更新 Excel 后重新运行批量分析并刷新页面即可。

已加载报告按 `period_key` 缓存在浏览器内存中。同一次页面会话再次选择该周期时直接使用缓存。

## 页面切换

标题下方包含两级控件：

1. 日、周、月分段按钮，并显示各粒度可用周期数量。
2. 当前粒度的周期选择器，按最新到最早展示。

切换粒度时默认进入该粒度最新周期，并记住用户在每个粒度最后查看的周期。没有报告的粒度保持禁用。

## 页面映射

| 页面区域 | 分析字段 | 要求 |
|---|---|---|
| 标题与元信息 | `meta.title`、周期字段、两侧 SPU | 必须 |
| 首屏优点 | `meta.summary` | 必须 |
| 首屏弱点 | `meta.weakness_summary` | 必须 |
| 四张指标卡 | `core_metrics[]` | 必须 |
| 流量来源 Tab | `tabs[id=traffic]` | 必须 |
| 关键词 Tab | `tabs[id=keywords]` | 完整看板必需 |
| 客户画像 Tab | `tabs[id=customer_profile]` | 完整看板必需 |
| AI核心判断与建议 | `diagnosis[]` | 必须 |
| 风险提示 | `risks[]` | 必须 |

## 展示约束

1. 本品值标记为真实值，竞品值标记为估算值。
2. `advantage`、`warning` 和 `neutral` 使用统一状态颜色。
3. 每个差距来源 Tab 先展示 3 至 5 项重点数据，再展示完整表格。
4. 客户画像完整表格支持性别、年龄、省份、城市切换。
5. `diagnosis[]` 分别展示证据和建议，不在网页端拼接业务结论。
6. 数值为 `null` 时显示 `-`，数值 `0` 正常显示。
7. 明细表格在自身容器内滚动，不造成页面级横向溢出。
8. 缺失模块保持空状态，并在页面底部显示 `risks[]`。

## Vite数据映射

Vite将 `/reports/` 只读映射到运行产物目录。网页使用以下地址：

```text
/reports/report-index.json
/reports/day/2026-06-01_2026-06-01/analysis_result.json
```

映射层只提供静态 JSON，不触发分析任务，不修改输出文件，也不暴露输入 Excel。
