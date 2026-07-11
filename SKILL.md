---
name: jd-competitor-analysis
description: 京东自营竞品分析通用工作流。用于读取日、周、月粒度的京东导出 Excel，按区间估算 SOP 生成每周期 normalized_data.json、analysis_result.json 和轻量报告索引，并检查数据缺口、计算约束和口径风险。适用于竞品准真实值估算、核心指标对比、流量来源分析、关键词分析、成交客户画像分析和多周期网页看板生成。
---

# 京东自营竞品分析


## 目录职责

| 目录 | 内容 |
|---|---|
| `assets/` | 会被复制、打开或直接消费的输出资源，包括 HTML 框架、空结构 JSON 和真实数据示例。 |
| `scripts/` | 可执行的数据发现、读取、估算、契约校验、运行数据和 Vite 看板代码。 |
| `references/` | Agent 按需读取的业务规则、字段映射和结构说明。 |

运行时原始 Excel 由调用方指定。每周期 JSON 和报告索引生成到 `scripts/output/`，该目录不进入版本控制。`assets/examples/` 保留一份用于回归验证的真实数据示例。

## 标准流程

1. 读取 `references/pipeline.md`，确认数据链路和模块边界。
2. 按 `references/normalized-data.md` 和 `references/field-map.md` 定位当前粒度、当前周期的源文件，生成 `normalized_data.json`。
3. 读取 `references/estimation.md`，按同周期同粒度口径计算本品 P、竞品候选值、成交公式约束和置信度。
4. 按 `references/analysis-result.md` 和 `references/field-map.md` 生成并校验 `analysis_result.json`。
5. 批量模式按粒度目录发现周期，每周期独立生成两份 JSON，并在全部周期完成后写入 `report-index.json`。
6. 检查核心必需数据、完整看板数据和诊断增强数据的可用状态；缺失项按映射规则降级并写入 `risks[]`。
7. 按 `references/dashboard.md` 检查日、周、月切换、周期选择、首屏、三个差距来源 Tab、AI 核心判断与风险提示。
8. 原始 Excel 全程只读，计算只在分析层完成，网页按需消费一份 `analysis_result.json`。

## 质量检查

每次生成结果后至少检查：

1. `normalized_data.json` 是否记录源文件和读取警告。
2. `analysis_result.json` 是否包含 `source_files`、`self_validation`、`competitor_core_conversions`、`core_metrics`、`traffic_sources`、`keywords`、`customer_profile`、`promotion`、`tabs`、`diagnosis` 和 `risks`。
3. 本品核心指标是否大部分落入本品区间。
4. HTML 是否只消费 JSON 结果，业务数字是否来自 `analysis_result.json`。
5. 缺失数据要写入风险说明，不要用推测补齐。
6. `report-index.json` 中的日、周、月数量是否与源目录的有效周期一致。

## 内置资产

| 文件 | 用途 |
|---|---|
| `assets/dashboard-template.html` | 正式网页看板框架，只消费 `analysis_result` 结构数据。 |
| `assets/dashboard-playground.html` | 日、周、月及各周期即时切换的独立交互演示页。 |
| `assets/examples/analysis-result.example.json` | 由真实原始 Excel 生成的完整周维度示例，用于联调和回归检查。 |
| `assets/analysis-result.template.json` | 不含业务值的空结构模板，保留 HTML 所需顶层字段、Tab 和列定义。 |
| `assets/report-index.template.json` | 不含业务值的日、周、月报告索引空结构。 |
| `scripts/excel_to_dashboard.py` | 发现六类真实 Excel，支持单周期和多粒度批量生成，并输出轻量报告索引。 |
| `scripts/pyproject.toml` | uv 项目配置和 Python 依赖声明。 |
| `scripts/uv.lock` | Python 依赖锁文件。 |
| `scripts/web/` | Vite 看板源码，读取 `scripts/output/` 并提供日、周、月及周期切换。 |

## 内部参考

| 文件 | 读取时机 |
|---|---|
| `references/pipeline.md` | 需要确认数据链路、JSON 分工和模块边界时读取。 |
| `references/normalized-data.md` | 需要生成或校验 Excel 标准化事实数据时读取。 |
| `references/analysis-result.md` | 需要生成或校验分析结果结构、必需字段和降级结构时读取。 |
| `references/field-map.md` | 需要核对 Excel 到标准化数据、标准化数据到分析结果的字段转换时读取。 |
| `references/estimation.md` | 需要核对区间解析、候选选择、约束校正和置信度时读取。 |
| `references/dashboard.md` | 需要维护 HTML 区域、交互和展示字段时读取。 |
