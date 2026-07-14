---
name: jd-competitor-analysis
description: 京东自营竞品分析通用工作流。用于读取日、周、月粒度的京东导出 Excel，按区间估算 SOP 生成每周期 normalized_data.json、analysis_result.json 和轻量报告索引，并检查数据缺口、计算约束和口径风险。适用于竞品准真实值估算、核心指标对比、流量来源分析、关键词分析、成交客户画像分析和多周期网页看板生成。
---

# 京东自营竞品分析

## 目录职责

| 目录 | 内容 |
|---|---|
| `assets/` | 会被脚本直接消费的 JSON 空结构和回归示例。 |
| `scripts/` | 可执行的数据发现、读取、估算、契约校验、运行数据和 Vite 看板代码。 |
| `references/` | Agent 按需读取的业务规则、字段映射和结构说明。 |

运行时原始 Excel 由调用方指定。每周期 JSON 和报告索引生成到 `scripts/output/`，该目录不进入版本控制。`assets/analysis-result.example.json` 保留一份用于回归验证的真实数据示例。

## 标准流程

1. 按 `references/normalized-data.md` 发现当前粒度和周期的输入文件，确认数据角色、表头、SPU 与周期，生成 `normalized_data.json`。
2. 读取 `references/estimation.md`，以同周期本品 P 候选为主，结合成交公式、流量来源和渠道层级约束生成竞品准真实估算值及置信度。
3. 按 `references/analysis-result.md` 生成并校验 `analysis_result.json`；基础分析阶段保持 `ai_recommendations` 为空数组。
4. 读取完整 `analysis_result.json` 与 `references/ai-recommendations.md`，独立分析指标结构，生成 1–5 条 `ai_recommendations`，再用 `scripts/apply_ai_recommendations.py` 写回当前报告。
5. 批量模式分别扫描天、周、月目录，每周期独立生成两份 JSON，并在全部周期完成后原子写入 `report-index.json`；正式展示的周期逐一完成 AI 建议步骤。
6. 按 `references/dashboard.md` 启动 Vite 看板，检查日、周、月切换、周期选择、首屏、三个差距来源 Tab、AI 建议和风险提示。
7. 原始 Excel 全程只读；估算只在分析脚本中完成；AI 建议只由 Skill 生成；网页只消费 JSON，不执行估算或拼接建议。

## 执行入口

批量生成日、周、月分析数据：

```powershell
uv run --project <Skill根目录>/scripts python <Skill根目录>/scripts/excel_to_dashboard.py `
  --batch --input-root <原始数据目录> --output-root <Skill根目录>/scripts/output `
  --self-spu <本品SPU> --competitor-spu <竞品SPU> --competitor-prefix <竞品字段前缀>
```

启动网页看板：

```powershell
cd <Skill根目录>/scripts/web
npm ci
npm run dev
```

## 质量检查

每次生成结果后至少检查：

1. `normalized_data.json` 是否记录源文件和读取警告。
2. `analysis_result.json` 是否符合 `references/analysis-result.md`，并包含稳定的 `promotion` 对象和 `ai_recommendations` 数组。
3. 本品核心指标落区间情况、竞品约束检查和最终置信度是否符合 `references/estimation.md`。
4. HTML 是否只消费 JSON 结果，业务数字是否来自 `analysis_result.json`。
5. 缺失数据要写入风险说明，不要用推测补齐。
6. `report-index.json` 中的日、周、月数量是否与源目录的有效周期一致。

## 内置资产

| 文件 | 用途 |
|---|---|
| `assets/analysis-result.example.json` | 由真实原始 Excel 生成的完整周维度示例，用于联调和回归检查。 |
| `assets/analysis-result.template.json` | 不含业务值的空结构模板，保留 HTML 所需顶层字段、Tab 和列定义。 |
| `assets/report-index.template.json` | 不含业务值的日、周、月报告索引空结构。 |
| `scripts/excel_to_dashboard.py` | 发现六类真实 Excel，支持单周期和多粒度批量生成，并输出轻量报告索引。 |
| `scripts/apply_ai_recommendations.py` | 校验 Skill 产出的结构化 AI 建议，并按周期安全写回 `analysis_result.json`。 |
| `scripts/pyproject.toml` | uv 项目配置和 Python 依赖声明。 |
| `scripts/uv.lock` | Python 依赖锁文件。 |
| `scripts/web/` | Vite 看板源码，读取 `scripts/output/` 并提供日、周、月及周期切换。 |

## 内部参考

| 文件 | 读取时机 |
|---|---|
| `references/normalized-data.md` | 需要发现输入文件、确认数据角色或生成标准化事实数据时读取。 |
| `references/estimation.md` | 需要核对区间解析、候选选择、约束校正和置信度时读取。 |
| `references/analysis-result.md` | 需要生成或校验最终分析 JSON、字段来源和降级结构时读取。 |
| `references/ai-recommendations.md` | 需要生成或校验结构化 AI 建议时读取。 |
| `references/dashboard.md` | 需要维护 HTML 区域、交互和展示字段时读取。 |
