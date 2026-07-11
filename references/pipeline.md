# 数据链路

## 数据链路

```text
源 Excel 数据
  -> 按日、周、月目录发现独立周期
  -> 每周期 normalized_data.json
  -> 每周期 analysis_result.json
  -> report-index.json
  -> Vite 网页按需加载
```

## JSON 分工

| 文件 | 说明 |
|---|---|
| `normalized_data.json` | 保存从 Excel 读取并标准化后的事实数据，尽量少做业务判断。 |
| `analysis_result.json` | 保存按当前 SOP 推导出的准真实值、差距、建议动作和风险说明。 |
| `report-index.json` | 保存日、周、月可用周期及每份分析结果的读取路径，不包含完整报告数据。 |

结构与转换规则分别见 [normalized-data.md](normalized-data.md)、[analysis-result.md](analysis-result.md) 和 [field-map.md](field-map.md)。

## 脚本边界

| 模块 | 职责 |
|---|---|
| 读取模块 | 定位 Excel、确认数据角色、筛选业务行并保留来源。 |
| 分析模块 | 解析区间，应用估算、约束、差距和建议规则。 |
| 索引模块 | 汇总周期键、日期、置信度和分析结果路径。 |
| Vite 网页 | 读取索引，并在用户切换粒度或周期时加载一份分析结果。 |

## 常见风险

1. 京东导出表只读模式可能误判维度，读取 Excel 默认使用 `read_only=False`。
2. `-` 表示缺失、低于阈值或未披露，不等同于 0。
3. 竞品区间值不能还原后台真实值，只能称为准真实值或可比估算值。
4. 日、周、月粒度不得共用同一套 P 参数。
5. 推广归因成交金额不一定等同核心 SPU 成交金额。

## 批量输出

批量模式分别扫描天、周、月目录，以核心对比文件发现周期。每个周期独立生成两份 JSON，最后原子写入报告索引。新增日报只增加对应日周期，不影响已有周报和月报。

```powershell
uv run --project jd-competitor-analysis/scripts `
  python jd-competitor-analysis/scripts/excel_to_dashboard.py `
  --batch `
  --input-root <原始数据目录> `
  --output-root jd-competitor-analysis/scripts/output `
  --start-date <YYYY-MM-DD> `
  --end-date <YYYY-MM-DD> `
  --self-spu <本品SPU> `
  --competitor-spu <竞品SPU> `
  --competitor-prefix <竞品字段前缀>
```

数据生成完成后，在 `jd-competitor-analysis/scripts/web/` 执行 `npm run dev` 启动看板。
