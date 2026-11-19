# Jev API 接入配置

独立 Python 工作流接收 Rec-Agent 导出的推荐 JSON。默认生成请求预览，指定 `--live` 后调用 Jev。[运行脚本](scripts/run_recommendation_workflow.py)

| 配置 | 值 |
| --- | --- |
| Endpoint | `https://api.modelgo.ai/v1/systemone` |
| Model | `jev-1.14.0` |
| Authorization | `Bearer $MODELGO_API_KEY` |
| Content-Type | `application/json` |
| 默认协议 | `jev-questions-v3-five-r1` |

请求通过 `model`、`state`、`questions` 发送。`state` 包含候选理由、商品与促销事实、最小场景、气候和时间、覆盖与规则线索、AI 披露、来源和版本。用户标识字段、推荐行为和离线评测标签留在本地。[输入字段清单](docs/JEV_JUDGMENT_PROTOCOL.md)

每条推荐对应一次请求。Jev 回答事实支持、表达风险、场景相关性、主要风险四道单选，以及一道吸引力评分。工作流用 0–5 六档的概率期望等级乘 20 得到 0–100 分，无分布时直接将标量乘 20。最终只有 `compliance=Y` 且吸引力严格大于 50 才会曝光。合规文案得 50 分时归为改写。已知硬风险和证据缺失按规则分别处置。历史九题可用 `--question-version jev-questions-v2` 显式选择。[题目与处置标准](docs/JEV_QUESTIONS.md)

## 使用示例

先生成请求预览，再检查 `jev_requests.jsonl` 中的事实与题目。

```bash
python3 scripts/run_recommendation_workflow.py \
  --input examples/harness_recommendations.json \
  --output-dir /tmp/rec-agent-jev-prepare
```

配置本机环境变量后，用新的输出目录调用模型。

```bash
export MODELGO_API_KEY="<your-api-key>"
python3 scripts/run_recommendation_workflow.py \
  --input examples/harness_recommendations.json \
  --output-dir /tmp/rec-agent-jev-live \
  --ai-disclosure unknown \
  --live
```

确认包含所需披露时使用 `visible`，确认缺少时使用 `missing`，展示配置还未确认时使用 `unknown`。未设置 `MODELGO_API_KEY` 时，真实调用会在发出请求前报错。

密钥通过当前终端的环境变量提供，Authorization header 只随 HTTP 请求发送。Adapter 校验 TLS 证书。原始模型响应和最终处置分别落盘，完整结果在 `workflow_results.json`。[独立工作流](docs/STANDALONE_WORKFLOW.md)
