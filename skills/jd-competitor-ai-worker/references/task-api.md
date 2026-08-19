# AI 任务接口

## 任务输入

领取成功后，客户端保存以下结构：

```json
{
  "task": {
    "analysis_id": "任务 ID",
    "dataset_id": "标准化数据集 ID",
    "source_hash": "输入数据哈希",
    "lease_token": "本次租约令牌",
    "lease_expires_at": "租约到期时间",
    "payload": {}
  }
}
```

`payload` 由后端生成，只读使用。不得修改或重新推导其中的确定性指标。

## 分析结果

`result.json` 必须是 UTF-8 JSON，结构如下：

```json
{
  "summary": "当前周期的整体判断",
  "findings": [
    {
      "source_id": "traffic",
      "target": "具体分析对象",
      "judgement": "基于事实的判断",
      "evidence": "可复核证据"
    }
  ],
  "recommendations": [
    {
      "source_id": "traffic",
      "source_label": "流量来源",
      "target": "具体渠道",
      "status": "warning",
      "evidence": "本品、竞品和差距",
      "actions": ["具体动作"],
      "validation": "后续复核指标和方向"
    },
    {
      "source_id": "keywords",
      "source_label": "引流关键词",
      "target": "具体关键词",
      "status": "warning",
      "evidence": "本品、竞品和差距",
      "actions": ["具体动作"],
      "validation": "后续复核指标和方向"
    }
  ]
}
```

顶层只允许表达 AI 生成的总结、发现和建议。任务 ID、数据哈希和租约由客户端从任务文件读取并随请求提交，不手工复制到结果文件。

证据不足时 `recommendations` 使用空数组；生成建议时必须包含 2–5 项并覆盖至少两个来源。Backend 保存 AI 原始结果，并将总结、发现和建议合并到基础报告；Mac 不读取或回传完整报告。

## 状态与重试

- 后端没有任务时，领取命令写出 `{ "task": null }`。
- 领取后任务进入 `processing`，只能使用当前租约提交。
- 租约到期后任务可以被重新领取；不要继续提交旧租约结果。
- 相同任务和相同结果可以重复回传，后端按幂等完成处理。
- `409` 表示状态、数据版本或租约冲突，应停止提交并重新领取。
- 分析本身失败时调用失败接口；网络失败不等同于分析失败。
