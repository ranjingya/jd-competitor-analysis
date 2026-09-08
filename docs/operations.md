# 部署与运维

## 部署文件

服务器部署目录为 `/home/yatui/jd-competitor-analysis`：

```text
.env
docker-compose.yaml
scripts/
  run-daily-analysis.sh
data/
  data.db
  daily-analysis-status.json
  deepseek-pricing.json
  product-images.json
  logs/
```

- 手动维护：`.env` 和 `data/product-images.json`。
- GitHub Actions 同步：Compose 文件、定时脚本和 DeepSeek 价格配置。
- 运行时生成：数据库、任务状态和日志。

Docker Compose 将 `.env` 注入 Backend 进程；宿主机脚本每次执行也读取该文件中的通知配置。Backend 容器直接使用进程环境变量。

Web 和 Backend 仅在 Docker 网络中开放服务端口。Traefik 连接 Web，Web 内的 Nginx 将 `/api` 转发到 Backend。两个容器的启动命令、网络和数据挂载见根目录 `docker-compose.yaml`。

## 商品主图

在 `data/product-images.json` 中按商品 SPU 维护完整 HTTPS 主图地址：

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-09-08",
  "products": {
    "商品 SPU": {
      "name": "商品名称",
      "image_url": "https://example.com/product.jpg"
    }
  }
}
```

日报任务启动时读取一次配置，将地址同步到已有报告，并用于本次报告生成。没有主图的商品使用缺图占位，报告正常生成。

修改后立即同步，在服务器部署目录执行：

```bash
docker compose exec -T jd-competitor-analysis-backend \
  python /app/cli.py sync-product-images
```

本地执行：

```bash
uv run --project backend python backend/cli.py sync-product-images
```

## 通知配置

宿主机 `.env` 中配置：

```dotenv
HEALTHCHECKS_PING_URL=https://hc-cron.kktree.cn/ping/<检查 UUID>
LARK_COMPLETION_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/<Webhook 标识>
LARK_COMPLETION_WEBHOOK_SECRET=<群机器人签名校验密钥>
DASHBOARD_URL=https://jd-comp.skills.kktree.cn/
LARK_APP_ID=<飞书自建应用 App ID>
LARK_APP_SECRET=<飞书自建应用 App Secret>
LARK_ALERT_OPEN_ID=<当前飞书应用下的用户 open_id>
```

- Healthchecks：接收任务开始、成功和失败请求；预期执行时间在 Healthchecks 中单独设置。
- 完成通知：日周月批次全部成功后向群机器人发送绿色卡片，包含商品对总数、实际处理日期的新增和无数据数量、生成时间（UTC+8）及在线看板链接。
- 失败通知：真正失败时向指定用户私聊发送告警，包含原因、时间、服务器、退出码和末尾日志摘要；失败时不发送群 Webhook。
- 无数据：记录处理结果，任务正常完成，不触发失败告警。

补数据和补 AI 成功均计为新增，全部已有的日期不展示；整体重试按日期和商品对去重，保留本次已成功的新增结果。周月报执行内容另行标明。

群机器人请求使用签名密钥和当前 Unix 时间生成签名；返回 `11232` 限流码时等待 30、60 秒后重试。通知异常只记录警告，不覆盖分析任务退出码。私聊接收人的 `open_id` 必须由当前应用查询得到，应用需要具有发送消息权限。

## 通知测试

在部署目录准备 `notification-result.json`，内容为模拟批次结果：

```json
{
  "total_pairs": 1,
  "results": [
    {
      "date": "2026-09-07",
      "self_spu": "10001",
      "competitor_spu": "20001",
      "status": "ready"
    }
  ]
}
```

仅向指定私聊发送测试卡片：

```bash
/bin/bash scripts/run-daily-analysis.sh --test-notification-private notification-result.json
```

向群机器人发送测试卡片：

```bash
/bin/bash scripts/run-daily-analysis.sh --test-notification notification-result.json
```

测试卡片标注“通知测试”。以上命令只发送通知，不读取数仓、不分析数据，也不向 Healthchecks 上报。

## 日志与权限

脚本运行日志保存在 `data/logs/`。DeepSeek 计费用量按月追加到 `data/logs/deepseek-usage-YYYY-MM.jsonl`，包含 Token、基础价格快照、契约校验状态和估算费用，不保存提示词或业务正文；价格取自 `data/deepseek-pricing.json`。

费用日志每次追加时设置为 `0644`。状态文件 `data/daily-analysis-status.json` 在后端启动时及每次写入时设置为 `0644`。宿主机用户可以读取这些文件，能否修改取决于文件所有者和权限；目录访问权限也需允许该用户进入。

宿主机、容器、日志及前端展示使用 `Asia/Shanghai`；数据库和 API 时间字段携带 `+08:00`。

在部署目录查看任务状态：

```bash
python3 -m json.tool data/daily-analysis-status.json
```

状态字段与 API 见[运行状态](warehouse.md#运行状态)，指定日期和商品的执行命令见[手动命令速查](warehouse.md#服务器手动命令速查)，失败处理见[日报生成门槛](warehouse.md#日报生成门槛)。
