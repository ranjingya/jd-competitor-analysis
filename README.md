# 京东竞品分析

本项目是一个前后端分离的竞品分析系统。服务器运行 Web 与 Backend 两个容器；宿主机定时启动 Backend CLI，依次完成数仓读取、确定性计算、DeepSeek 分析和报告入库。

## 目录

```text
web/      Vite 看板与内部 Nginx
backend/  FastAPI、批处理、StarRocks 访问、DeepSeek 调用和数据持久化
docs/     数据、估算、报告和看板契约
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

## 商品主图配置

商品主图在 `backend/assets/product-images.json` 中按商品 ID 维护：

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-08-21",
  "products": {
    "商品 ID": {
      "name": "商品名称",
      "image_url": "https://example.com/product.jpg"
    }
  }
}
```

`image_url` 使用完整 HTTPS 地址，可以直接手动增加或修改。商品没有配置主图时，报告正常生成，Web 使用缺图占位。日分析任务启动时读取一次该文件，已经入库的报告继续使用生成报告时保存的主图地址。

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

## 日分析任务

完整日分析由 Backend CLI 在独立进程中执行：

```text
飞书与 StarRocks → 标准化 → 固定公式 → DeepSeek → 最终报告
```

生产环境由宿主机 cron 使用 `docker compose exec` 启动 CLI。FastAPI 持续提供只读报告接口，不通过 Web 请求触发长时间分析。

## 已有能力

- Web 已通过 `/api/reports` 读取报告。
- Backend 已提供报告查询 API 和完整日分析 CLI。
- 标准化日数据、AI 执行记录和看板报告统一保存在 `data/backend.db`。
- 同一日期和商品对只有一份当前报告及一条非过期 AI 执行记录。
- StarRocks 连接探测和原 Excel 分析逻辑保留在 Backend。
- `warehouse-daily-run` 按商品对串行完成数仓读取、固定公式、DeepSeek 分析和报告入库。
- 日分析使用进程锁防止同一服务器重复执行，单个商品对失败后继续处理下一组。
