# 网页看板

## 定位

网页看板位于 `web/`，只负责展示 Backend 返回的数据，不读取 Excel、标准化中间数据或服务器文件，也不执行估算和 AI 分析。

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
  → GET /api/reports
  → 默认选择最新日报；没有日报时选择第一个有数据的粒度
  → GET 当前索引条目的 path
  → 渲染完整报告
```

报告索引包含 `day`、`week` 和 `month` 三个数组。每个条目的 `path` 由 Backend 生成，例如：

```json
{
  "period_key": "week:2026-08-10_2026-08-16",
  "path": "/api/reports/week/2026-08-10_2026-08-16"
}
```

## 展示约束

1. 本品值标记为真实值，竞品值标记为估算值。
2. 缺失值显示为 `-`，数值零正常显示。
3. 页面只展示 Backend 返回的 AI 结果，不拼接或回退到模板建议。
4. 缺失模块保持空状态，并展示对应风险说明。
5. 已加载报告可以在当前页面会话中按 `period_key` 缓存。
