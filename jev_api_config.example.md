# Jev API 配置

独立工作流导入 Rec-Agent 推荐 JSON，构建事实包并调用 Jev。每条推荐包含风险分型与吸引力两题，详见[审核协议](docs/JEV_JUDGMENT_PROTOCOL.md)。

| 配置 | 值 |
| --- | --- |
| Endpoint | `https://api.modelgo.ai/v1/systemone` |
| Model | `jev-1.14.0` |
| Authorization | `Bearer $MODELGO_API_KEY` |
| Content-Type | `application/json` |
| 问题协议 | `jev-questions-v4-two` |

## 请求预览

在项目根目录执行：

```bash
python3 scripts/run_recommendation_workflow.py \
  --input examples/harness_recommendations.json \
  --output-dir runs/jev-preview
```

默认仅生成事实包和请求预览。`jev_requests.jsonl` 保存实际的 `model`、`state`、`questions`。

## 模型调用

通过进程环境提供密钥，并为每次运行使用新的输出目录：

```bash
export MODELGO_API_KEY="<your-api-key>"
python3 scripts/run_recommendation_workflow.py \
  --input examples/harness_recommendations.json \
  --output-dir runs/jev-live \
  --ai-disclosure unknown \
  --live
```

`--ai-disclosure` 按实际展示配置设置：

| 值 | 含义 |
| --- | --- |
| `visible` | 已确认显示所需 AI 披露。 |
| `missing` | 已确认缺少所需 AI 披露。 |
| `unknown` | 展示配置待确认，默认值。 |

密钥保留在本机环境中；Adapter 使用 TLS 校验发送请求。未设置密钥时，`--live` 会在调用前报错。完整结果保存于 `workflow_results.json`，包括推荐、Jev 风险类别、吸引力和处置。

[工作流使用说明](docs/STANDALONE_WORKFLOW.md) · [题目与评分标准](docs/JEV_QUESTIONS.md)
