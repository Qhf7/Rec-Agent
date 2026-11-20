# Jev 审核速览

Jev 在推荐生成完成后独立审核，每条推荐回答两题，工作流将答案汇总为最终处置。

| 题目 | 类型 | 输出 |
| --- | --- | --- |
| 风险分型 `risk_type` | 六选一 | `compliant`、`absolute_claim`、`efficacy_or_medical_claim`、`price_misleading`、`missing_ai_disclosure`、`off_topic` |
| 文案吸引力 `attractiveness_score` | 有序等级评分 | 映射为业务分 1–100；评价卖点与文案表达。 |

**最终规则：`risk_type=compliant` 且吸引力严格大于 50 时为 `expose`，其余为 `rewrite`。** 合规字段 `compliance` 分别为 `Y` 或 `N`。

模型接收待审曝光理由、商品事实、有效促销规则、精简用户场景、气候及时间、披露状态、来源与版本。历史曝光点击和完整行为数据供推荐 Agent 使用，不传给 Jev。

| 参考文档 | 内容 |
| --- | --- |
| [题目与评分标准](JEV_QUESTIONS.md) | 六类风险边界、评分参考、10 档等级到 1–100 分的换算。 |
| [输入与输出契约](JEV_JUDGMENT_PROTOCOL.md) | 实际输入白名单、数据范围、答卷及处置字段。 |
| [独立工作流](STANDALONE_WORKFLOW.md) | 导入推荐、预览请求、调用模型与读取结果。 |
| [API 配置](../jev_api_config.example.md) | 模型端点、凭据及调用命令。 |
