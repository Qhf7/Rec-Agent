# Jev API 接入配置

推荐 Agent 只输出候选 JSON。Jev 审核由独立 Python 工作流运行，默认生成请求预览；显式 `--live` 才请求模型。

## 当前配置与验证边界

- Endpoint：`https://api.modelgo.ai/v1/systemone`
- Model：`jev-1.14.0`
- Authentication：`Authorization: Bearer $MODELGO_API_KEY`
- Content-Type：`application/json`

当前采用九题标量协议，已保存真实API响应用于验证和回放。模型处置与逐题判断见 [当前工作流验证报告](docs/TEST_REPORT_JEV_MODEL_WORKFLOW_2026-11-18.md)。

官方格式参考：[System One API](https://docs.typesafe.ai/api/system-one)、[Choice](https://docs.typesafe.ai/primitives/choice)、[Score](https://docs.typesafe.ai/primitives/score)。

## 输入与问题

外层请求只有 `model`、`state`、`questions`。版本保存在 `state` 内，不增加自定义 API 顶层字段。

`state` 由 `jev_protocol.build_jev_input` 从事实包白名单构建：候选理由、商品事实、最小场景、规范气候/时间、促销条件、规则特征、覆盖、披露与来源。用户 ID、历史点击/CTR、曝光统计、订单退款投诉、购物车搜索、排序分与评测标签均不能进入输入。

`questions` 使用官方标量格式：

```json
{
  "q1_identity": {
    "type": "choice",
    "instructions": "核验候选与事实是否一致可追溯",
    "criteria": {
      "valid": "身份与版本一致",
      "invalid": "身份或版本冲突",
      "unverifiable": "证据不足"
    }
  }
}
```

实际固定问题由 `build_jev_questions()` 定义：Q1 身份、Q2 事实支持、Q3 表达风险、Q4 商业准确性、Q5 场景相关性、Q6 安全门禁、Q7 最终建议，另有 `risk_type` Choice 和 `judge_score` Score。共八个 Choice 和一个 Score；各问并行判断，最终 `decision` 直接采用 Jev 的 `q7_final_decision.choice`。

Score 使用三级描述（0/1/2），代码从返回分布计算等级期望值并除以 2。`judge_score` 是风险严重度，不是已校准违规概率。每题置信度、Q7置信度和最低置信度单独保留。`human_review` 只是模型处置标签；工作流保存模型结果后结束。

## 运行

```bash
python3 scripts/run_recommendation_workflow.py \
  --input examples/harness_recommendations.json \
  --output-dir /tmp/rec-agent-jev-prepare
```

先检查候选、事实包与请求预览；真实调用在新目录执行：

```bash
export MODELGO_API_KEY="<your-api-key>"
python3 scripts/run_recommendation_workflow.py \
  --input examples/harness_recommendations.json \
  --output-dir /tmp/rec-agent-jev-live \
  --ai-disclosure visible \
  --live
```

只有实际展示配置包含所需 AI 披露时才选择 `visible`；也可选择 `missing`。默认 `unknown` 不推测披露已存在。

结果中的 `evidence_source` 说明证据来源。官方 Choice 不生成自由文本证据，默认 `workflow_fact_snapshot` 由工作流呈现已提供事实与规则线索；它不声称是模型逐句引用。新真实请求仅接受完整标量协议，旧三问只在离线兼容入口解析。

环境变量只在当前终端设置。密钥不写入仓库；Adapter 保持 TLS 证书校验。产物与异常不含 Authorization header。完整产物说明见 [独立工作流](docs/STANDALONE_WORKFLOW.md)。
