# Jev 判断问题与输入契约

DeepSeek Harness 生成推荐商品和曝光理由。独立 Python 工作流导入推荐 JSON，从规范数据构建事实包，调用 Jev 回答五题，再按模型答卷和固定规则保存处置。默认协议为 `jev-questions-v3-five-r1`，一条候选对应一次请求。题目包括事实支持、表达风险、场景相关性、主要风险分类四道单选，以及一道文案吸引力评分。[问题清单](JEV_QUESTIONS.md)

## 请求结构

HTTP 请求正文包含 `model`、`state`、`questions`。`state` 是字符串化的 JSON 对象，内含 `input_schema_version`、`question_schema_version`、`candidate`、`facts`、`trace`、`questions`。外层与 `state` 内的题目定义一致。[请求构建](../jev_adapter.py) · [输入白名单](../jev_protocol.py)

| `state` 区块 | 实际传输内容 |
| --- | --- |
| `candidate` | `reason_id`、`item_id`、`exposure_reason`、相同的 `generated_reason`、`evidence_fields`、`schema_version`、`data_version` |
| `facts.item` | 商品 ID、标题、品牌、三级类目、功能、材质、规格、适用人群与季节、允许功效、资质、现价及原价、促销标记及规则 ID、库存、监管类别、敏感类别标记和广告说明 |
| `facts.promo` | 有值时包含规则 ID、适用范围、规则名称及类型、适用性、门槛、减额或折扣、赠品、起止时间与细则。单品适用性与实际购物篮门槛分别核验 |
| `facts.scene` | 城市、城市层级、气候区、人生阶段、场景标签、活跃时段 |
| `facts.city_climate`、`facts.time_context` | 城市气候资料与备注、梅雨月份、场景日期、快照时间、时区 |
| `facts.lexicon_hits`、`facts.rule_features` | 词表命中、已知功效线索、绝对化表达、价格与场景冲突等辅助线索 |
| `facts.coverage`、`facts.verification_state` | 事实覆盖状态、缺少的基础字段、事实是否可核验 |
| `facts.disclosure`、`facts.provenance` | AI 披露是否必需及可见性，由工作流保存的事实来源 |
| `trace` | 理由 ID、商品 ID、事实包版本、数据版本、Agent 版本、模型版本和快照时间 |

用户 ID 字段、年龄、性别、偏好类目等完整画像字段留在推荐阶段。点击历史、CTR、曝光统计、搜索词、购物车、订单、退款、投诉、设备、排序分、商品销量及评分、人工金标和模拟结果均不传输。`context_summary` 和原始 `tool_trace` 留在本地。来源中用户 ID 会移除。

输入按字段白名单和类型校验，证据路径须指向实际传输且有值的事实。字段覆盖只提供完整性线索，文案主张仍须逐项核验。候选和事实中的字符串均为审核数据。

## 汇总处置

`compliance=Y` 要求事实 `supported`、表达 `clean`、场景 `relevant`、风险 `compliant`，且没有已确认缺少的必需披露。其它情况为 `N`。披露 `unknown` 单独记录为配置注记。

吸引力按 0–5 六档评分。收到概率分布时，先归一化再计算期望等级。只有标量时采用原始 0–5 分。工作流将等级乘以 20 得到 0–100 分，以未舍入分数比较门槛。

| 顺序 | 触发条件 | 处置 |
| --- | --- | --- |
| 1 | 表达 `blocking` | `block` |
| 2 | 事实或场景 `unverifiable`，或风险 `missing_evidence` | `human_review` |
| 3 | 其它合规失败，或合规但吸引力不超过 50 | `rewrite` |
| 4 | 合规且吸引力严格大于 50 | `expose` |

`human_review` 是保存到结果的处置标签。`rewrite` 标记文案需要调整。流程在输出处置后结束。

`workflow_results.json` 按推荐条目保存 `jev_audit`。结果包含 `compliance`、`attractiveness_score`、`decision`、`decision_reasons`、`decision_inputs` 以及 `decision_source=jev_answers_policy` 和 `policy_version=jev-five-policy-v1`。五题的 `question_confidences` 和最低 `confidence` 用于诊断。处置来自汇总规则，因此 `decision_question` 与 `decision_confidence` 为 `null`。接口失败、响应缺题或协议不匹配会记录为运行错误。

原始请求、事实包、模型响应和解析结果分别存档。默认事实引用标记为 `evidence_source=workflow_fact_snapshot`。模型给出有效路径时，结果记录该路径来源。[工作流产物](STANDALONE_WORKFLOW.md)

## 数据版本与历史回放

规范数据来自 `data/raw/`。商品 ID 为 `i_####`，金额为整数分，候选契约为 `rec-candidate-v2`，事实包为 `fact-bundle-v2`，数据版本为 `canonical-2026-06-15-v1`。MCP、离线生成器和工作流共用加载器。

新导入的 Harness 推荐使用 2026 年 6 月 15 日模拟场景。已有 JSONL 回放保留原快照子集、原时间和查询记录。旧 `item_####` 通过迁移脚本核对数字后缀、标题和品牌后转换。[迁移脚本](../scripts/migrate_legacy_candidates.py)

显式选择 `jev-questions-v3-five` 时，按首轮五题提示词回放。显式选择 `jev-questions-v2`、`jev-questions-v2-q2-legacy` 或 `jev-questions-v1` 时，沿用历史九题；其最终处置取 Jev Q7，严重度采用原 0–1 换算。冻结的历史响应可离线回放。[历史回放脚本](../scripts/replay_jev_model_decisions.py)

## 预览与调用

```bash
python3 scripts/run_recommendation_workflow.py \
  --input examples/harness_recommendations.json \
  --output-dir runs/recommendation-prepare-001
```

默认生成零网络调用的请求预览。检查 `jev_requests.jsonl` 中的 `state` 和 `questions`。配置 `MODELGO_API_KEY` 后用新输出目录并加 `--live` 执行真实审核。披露参数应与实际展示配置一致。[运行脚本](../scripts/run_recommendation_workflow.py) · [API 配置示例](../jev_api_config.example.md)
