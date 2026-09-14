# 京东竞品分析

从 StarRocks 读取京东商智数据，按固定公式计算竞品估算值，由 DeepSeek 生成分析建议，在 Web 看板展示日、周、月报告。

## 本地运行

准备 Python 环境管理工具 uv 和 Node.js，将根目录 `.env.example` 复制为 `.env` 并填写配置。

启动后端：

```bash
uv run --project backend uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```bash
cd web
npm ci
npm run dev
```

打开终端显示的前端地址。页面通过 `/api` 访问后端；生成报告的命令见[手动命令速查](docs/warehouse.md#服务器手动命令速查)。

## 服务器部署

Web 与 Backend 分别运行在两个容器中，Traefik 提供访问入口，数据持久化到宿主机 `data/`。

在部署目录准备 `.env`、`docker-compose.yaml`、`scripts/` 和 `data/`，然后执行：

```bash
docker compose up -d
```

GitHub Actions 在推送 `v*` 标签后构建镜像并部署。文件配置及权限说明见[部署与运维](docs/operations.md)。

## 定时运行

在服务器部署目录手动执行完整任务：

```bash
/bin/bash scripts/run-daily-analysis.sh
```

部署用户通过 `crontab -e` 设置每天北京时间 12:00 执行（宿主机时区需为 `Asia/Shanghai`）：

```cron
0 12 * * * /home/yatui/jd-competitor-analysis/scripts/run-daily-analysis.sh
```

每天检查最近七天日报、上一个完整自然周和自然月；周月报要求周期内每天的日报均已完成。Healthchecks 记录任务状态，完成通知发到飞书群，失败告警发到指定私聊。

## 文档

- [部署、主图维护、通知测试与日志](docs/operations.md)
- [数仓配置与手动命令](docs/warehouse.md)
- [系统架构与 API](docs/architecture.md)
- [数据库设计](docs/database-design.md)
- [估算规则](docs/estimation.md) · [标准化数据](docs/normalized-data.md) · [分析结果](docs/analysis-result.md)
- [看板说明](docs/dashboard.md)
- [运营分析 SOP 与建议规则](docs/operations-sop.md)
