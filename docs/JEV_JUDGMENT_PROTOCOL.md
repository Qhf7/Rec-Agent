# Jev 输入与输出契约

Rec-Agent 生成商品推荐与曝光理由，独立工作流从规范数据重建事实包，再调用 Jev。每条推荐使用 `jev-questions-v4-two` 协议回答风险分型与吸引力两题。

## 请求结构

HTTP 正文包含 `model`、`state`、`questions`。`state` 是序列化的 JSON 对象，包含以下字段：

```text
state
├── input_schema_version
├── question_schema_version
├── candidate
├── facts
├── trace
└── questions
```

外层与 `state.questions` 使用同一份题目定义。完整字段白名单及类型校验见 [`jev_protocol.py`](../jev_protocol.py)。

## 模型可见信息

| 区块 | 内容 | 作用 |
| --- | --- | --- |
| `candidate` | `reason_id`、`item_id`、曝光理由、内容相同的 `generated_reason`、证据字段、候选及数据版本 | 确定待审内容。 |
| `facts.item` | 标题、品牌、三级类目、功能、材质、规格、适用人群及季节、允许功效、资质、价格、促销标记、库存、监管类别及广告说明 | 核验商品主张，评价卖点表达。 |
| `facts.promo` | 促销 ID、名称、类型、范围、适用性、门槛、折扣、赠品、起止时间及细则 | 核验商业表达。单品参与活动与购物篮达到门槛分别判断。 |
| `facts.scene` | 城市、城市层级、气候区、人生阶段、场景标签、活跃时段 | 核验使用场景和个性化主张。 |
| `facts.city_climate`、`facts.time_context` | 气候资料、梅雨月份、场景日期、快照时间和时区 | 判断气候、季节及活动时效。 |
| `facts.lexicon_hits`、`facts.rule_features` | 词表命中、功效线索、绝对化表达、价格及场景冲突等特征 | 辅助定位待核验内容。 |
| `facts.coverage`、`facts.verification_state` | 缺少字段、覆盖状态及来源核验状态 | 标记事实可用性。 |
| `facts.disclosure`、`facts.provenance` | AI 披露要求、可见状态及受限事实来源 | 判断披露风险并关联事实来源。 |
| `trace` | 商品及理由 ID、事实包/数据/Agent/模型版本、快照时间 | 关联请求与结果。 |

输入采用字段白名单。证据路径必须指向实际传输且有值的事实，词表与规则特征用于辅助核验，候选文案及事实中的文本均作为数据处理。

### 推荐数据与审核数据

用户历史曝光点击、CTR、已展示/忽略商品、搜索词、购物车、订单和其他反馈供推荐阶段使用，**不传给 Jev**。Jev 接收上表中的精简场景信息。

用户 ID、完整年龄/性别/偏好画像、设备、销量、商品评分、排序分和评测标签也不在传输白名单内。`context_summary` 与原始工具轨迹留在本地；来源中的用户标识会移除。因此，吸引力分评价文案表达，不能解释为基于历史行为的个性化点击预测。

## 答卷与最终处置

Jev 返回 `risk_type` 六选一及 `attractiveness_score` 等级分，并提供每题置信度及可用的等级概率。模型评分索引 `0…9` 映射到业务分 `1…100`；计算方法见[题目与评分标准](JEV_QUESTIONS.md)。

规则 `jev-two-policy-v1` 使用两题答案汇总：

```text
compliance = Y  当 risk_type = compliant；否则为 N
decision = expose  当 compliance = Y 且 attractiveness_score > 50；否则为 rewrite
```

最终处置只使用模型风险选项与吸引力分数。每题置信度、披露配置和事实覆盖状态保留为信息字段，披露缺失由模型在风险题中判断。

## 结果字段

`workflow_results.json` 将每条推荐与对应的 `jev_audit` 放在一起。

| 字段 | 说明 |
| --- | --- |
| `risk_type` | Jev 选择的主要风险类别。 |
| `compliance` | 风险为 `compliant` 时为 `Y`，其余为 `N`。 |
| `attractiveness_score` | 映射后的 1–100 分吸引力。 |
| `decision` | `expose` 或 `rewrite`。 |
| `decision_source` | `jev_answers_policy`，表示由 Jev 答卷按固定规则汇总。 |
| `decision_reasons`、`decision_inputs` | 触发处置的选项、分数及门槛。 |
| `policy_version`、`protocol_completeness` | 汇总规则和问题协议版本。 |
| `question_choices`、`question_confidences`、`question_probabilities` | 原始选择、逐题置信度及有效概率。 |
| `evidence`、`evidence_source` | 有效事实引用及来源。`model_field_selection` 表示模型选取字段，`workflow_fact_snapshot` 表示工作流事实快照。 |
| `model_version`、`reason_id` | 模型版本与理由标识。 |

`decision_question`、`decision_confidence` 为 `null`，汇总置信度另存于 `confidence`；兼容字段 `escalated` 固定为 `false`。接口失败、缺题、多题或分数无效时记录运行错误。

`rewrite` 是结果标签，调用方负责后续改写和展示。请求、事实包、原始响应与解析结果分别保存，文件说明见[独立工作流](STANDALONE_WORKFLOW.md)。

## 数据契约

规范源为 `data/raw/`，商品 ID 使用 `i_####`，金额使用整数分。候选版本为 `rec-candidate-v2`，事实包版本为 `fact-bundle-v2`，当前数据版本为 `canonical-2026-06-15-v1`。工作流使用数据集的业务日期与事实快照，字段说明见[数据文档](../data/README.md)。

[API 配置](../jev_api_config.example.md) · [题目定义](JEV_QUESTIONS.md) · [使用说明](STANDALONE_WORKFLOW.md)
