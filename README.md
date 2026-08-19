# 京东竞品分析

本项目是一个前后端分离的竞品分析系统。服务器运行 Web 与 Backend 两个容器；Mac 上的 Codex Skill 作为外部 AI Worker，主动领取后端任务并回传分析结果。

## 目录

```text
web/           Vite 看板与内部 Nginx
backend/       FastAPI、确定性分析、StarRocks 访问和任务持久化
skills/jd-competitor-ai-worker/   Mac Codex 使用的 AI Worker Skill
docs/          数据、估算、报告和看板契约
```

## 本地运行

复制根目录 `.env.example` 为 `.env`，然后启动后端：

```bash
uv run --project backend uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

另一个终端启动前端：

```bash
cd web
npm ci
npm run dev
```

前端只访问同源 `/api`。Vite 开发服务器将该路径转发到 `127.0.0.1:8000`；生产环境由 Web 容器内的 Nginx 转发到 Backend 容器。

## 部署

服务器部署目录保存：

```text
.env
docker-compose.yaml
data/
```

启动服务：

```bash
docker compose up -d
```

两个服务都只使用 Docker 网络中的 `expose`，不直接向宿主机发布端口。Traefik 只连接 Web 容器，Backend 通过内部网络接受 `/api` 转发。

## Mac AI Worker

将 `skills/jd-competitor-ai-worker/` 安装或链接到 Mac 的 Codex Skills 目录，并复制其中的 `.env.example` 为 `.env`。Codex 定时任务调用 Skill 后执行以下闭环：

```text
领取任务 → 基于结构化事实分析 → 回传结果 → 继续领取
```

Skill 不连接 StarRocks，也不重新计算业务指标。接口路径直接使用 `/api`，当前不包含版本号。

## 已有能力

- Web 已通过 `/api/reports` 读取报告。
- Backend 已提供报告查询、任务领取、完成和失败接口。
- 标准化日数据、AI 任务和看板报告统一保存在 `data/backend.db`。
- AI 任务包含数据集关联、租约、数据哈希和幂等完成约束。
- StarRocks 连接探测和原 Excel 分析逻辑保留在 Backend。
- `warehouse-daily-run` 可以把数仓日数据、固定公式报告和待处理 AI 任务写入统一数据库。
