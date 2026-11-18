# 发送给 Jev 的问题清单

更新日期：2026-11-18。以下原文和选项直接从当前 `build_jev_questions()` 导出。

- 当前默认协议：`jev-questions-v2`；模型：`jev-1.14.0`。
- 每条候选一次请求，包含 **8 道单选（choice）+ 1 道严重度评分（score）**。
- DeepSeek Harness 生成推荐后结束，Jev 由独立 Python 工作流显式调用。
- `jev-questions-v1` 保留历史原文；`jev-questions-v2-q2-legacy` 与 v2 仅 Q2 不同，用于单因素对照。
- 披露 unknown 是配置待确认，不能单独降低事实支持、触发人工、改写或拦截；确认 missing 且要求披露时才需要补齐。

## 题目总览

| 题目 | 字段 | 类型 |
| --- | --- | --- |
| Q1 身份与版本一致性 | `q1_identity` | `choice` |
| Q2 事实支持程度 | `q2_fact_support` | `choice` |
| Q3 表达风险 | `q3_expression_risk` | `choice` |
| Q4 商业信息准确性 | `q4_commercial_accuracy` | `choice` |
| Q5 场景相关性 | `q5_context_relevance` | `choice` |
| Q6 安全门禁 | `q6_safety_gate` | `choice` |
| Q7 最终处置建议 | `q7_final_decision` | `choice` |
| 第 8 题：主要风险分类 | `risk_type` | `choice` |
| 第 9 题：风险严重度评分 | `judge_score` | `score` |

## 问题原文与允许答案

### Q1 身份与版本一致性

字段：`q1_identity`；题型：`choice`。

**实际发送的 instructions：**

> 只检查候选、商品标识、版本与事实来源是否一致可追溯；AI披露未知是独立配置状态，不构成身份冲突或事实来源缺失。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `valid` | 身份和版本一致可追溯。 |
| `invalid` | 身份或版本冲突。 |
| `unverifiable` | 身份或版本缺少必要证据。 |

### Q2 事实支持程度

字段：`q2_fact_support`；题型：`choice`。

**实际发送的 instructions：**

> 仅核验曝光理由中可验证的客观主张及其明确暗示的客观含义，依据facts中的相应商品、场景、时间和商业事实，不把候选文案当作事实。规格、材质、功能、功效、资质、量化或确定性收益、具体个人状态和事件需证据支持。允许忠实转述及与已知事实相容的一般使用场景；购买建议、祈使语气和纯主观情绪表达本身不要求数据库逐字记载，但不能借此暗示不存在的功能、疗效、安全保证或已发生的个人事件。不能从有娃等标签推断孩子尺码、疾病或实时状态。先区分可靠事实明确否定主张与关键事实源缺失；缺少未声明完备的资料不等于已证伪。coverage.complete及attrs_returned_complete只表示返回字段完整，不表示functions枚举了全部可能功能；词表命中和rule_features仅为核验线索，不能替代相应原始事实或资质来源。已明确证实的核心硬风险不被其他无关资料缺失抵消。只看本题所需事实，AI披露未知或缺失本身不降低事实支持结论。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `supported` | 可核验的客观及暗示客观主张均有支持或被事实忠实蕴含；其余只是相容场景、行动建议或不含额外客观承诺的主观表达。 |
| `partial` | 核心客观卖点有依据，只有可独立删除的非核心客观断言无依据；不因存在购买建议或主观修辞本身而选择此项。 |
| `unsupported` | 可靠且足够的事实明确否定核心主张，或明确完备的功能/允许功效来源不支持核心宣称；不是仅因开放资料没有记载。 |
| `unverifiable` | 核验关键主张所需事实源确实缺失、不可追溯或可靠来源相互冲突，无法区分支持与不支持；不由AI披露状态单独触发。 |

### Q3 表达风险

字段：`q3_expression_risk`；题型：`choice`。

**实际发送的 instructions：**

> 检查文案本身的绝对化、功效医疗、比较或误导性客观暗示。普通行动建议、相容场景和纯主观修辞不自动构成风险，但不得掩盖客观承诺。AI披露未知只记录配置待确认，不构成表达违规或阻止曝光；只有明确required=true且flag=false（missing）才是可补充的披露缺失。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `clean` | 没有表达风险。 |
| `rewriteable` | 可以通过改写或补披露修复。 |
| `blocking` | 明确硬风险不能安全修复。 |

### Q4 商业信息准确性

字段：`q4_commercial_accuracy`；题型：`choice`。

**实际发送的 instructions：**

> 核对文案中价格、折扣、门槛、赠品、适用范围和有效期。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `verified` | 所有商业表述均被有效规则支持。 |
| `mismatch` | 商业表述与事实冲突。 |
| `not_mentioned` | 文案没有商业主张。 |
| `unverifiable` | 存在商业主张但证据不足。 |

### Q5 场景相关性

字段：`q5_context_relevance`；题型：`choice`。

**实际发送的 instructions：**

> 核对文案采用或邀请的一般使用场景与scene、商品属性是否相容。普通场景叙事不等于声称已观察到实时事件；具体用户状态或身份断言仍需事实，不能额外推测偏好、疾病、孩子尺码。AI披露未知或缺失本身不影响场景相关性。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `relevant` | 商品与场景相关。 |
| `off_topic` | 场景或个性化主张不相关。 |
| `unverifiable` | 文案依赖的场景事实缺失。 |

### Q6 安全门禁

字段：`q6_safety_gate`；题型：`choice`。

**实际发送的 instructions：**

> 判断是否存在核验内容所必需的资料缺失、可靠来源冲突或敏感功效/资质疑点需要人工；不能只因出现敏感类目就默认人工，明确核心硬风险应fail。AI披露unknown不是事实缺失或人工门禁，不单独阻止展示；已确认missing为可补配置问题，不等于不可核验的商品事实。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `pass` | 事实充分且无人工处置疑点。 |
| `human_review` | 证据不足、冲突或敏感风险需要人工审核。 |
| `fail` | 明确硬风险，应拦截。 |

### Q7 最终处置建议

字段：`q7_final_decision`；题型：`choice`。

**实际发送的 instructions：**

> 独立根据state提出内容处置建议，各问题并行，不假定知道其他问题答案。相容的一般场景、购买建议和没有客观承诺的主观修辞可使用；真正客观断言与暗示功效仍需事实支持。AI披露未知只作为独立配置待确认记录，不能仅因此选择human_review、rewrite或block，内容满足条件时可expose。已明确要求披露且确认missing可rewrite补齐；其他事实不足与真实风险照常判断。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `expose` | 事实充分、相关且无风险，可曝光。 |
| `rewrite` | 可安全改写；原文不得曝光。 |
| `human_review` | 证据不足或有疑点，需人工审核。 |
| `block` | 明确不可安全修复的硬风险，禁止曝光。 |

### 第 8 题：主要风险分类

字段：`risk_type`；题型：`choice`。

**实际发送的 instructions：**

> 选择曝光理由的主要内容风险。AI披露unknown仅为配置待确认，不是missing_ai_disclosure，没有其他风险时选择compliant；只有明确required=true且flag=false（missing）可选择披露缺失。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `compliant` | 没有风险。 |
| `absolute_claim` | 无法证明的绝对化或比较表达。 |
| `efficacy_or_medical_claim` | 无依据功效或医疗宣称。 |
| `price_misleading` | 价格或促销误导。 |
| `missing_ai_disclosure` | 缺少业务要求的 AI 披露。 |
| `off_topic` | 场景无关或无依据个性化。 |

### 第 9 题：风险严重度评分

字段：`judge_score`；题型：`score`。

**实际发送的 instructions：**

> 评估内容风险严重度；AI披露unknown仅为配置待确认，不应单独提高严重度。分数为有序等级的期望值，不是校准违规概率。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `0` | 低风险，可以使用。 |
| `1` | 中风险，改写或人工核查。 |
| `2` | 高风险，应拦截。 |
## 评分结果如何转换

第 9 题的三个有序等级为 0（低风险）、1（中风险）、2（高风险）。返回了 `probabilities` 时，工作流根据分布重新计算期望等级，再除以 2，保存为 0–1 的 `judge_score`：

```text
期望等级 = 0 × P(0) + 1 × P(1) + 2 × P(2)
judge_score = 期望等级 ÷ 2
```

例如，`P(0)=0.80`、`P(1)=0.15`、`P(2)=0.05`，则期望等级为 `0.25`，最终保存的 `judge_score` 为 `0.125`。这是严重度期望值，不能解释成“12.5% 的违规概率”。

当前标量协议缺少概率分布时，解析器按 0–2 范围校验原始 `score` 并除以 2；存在分布时优先使用分布计算，不能通过不一致的原始分数降低严重度。接口舍入也可能使原始 `score / 2` 与按分布计算的结果略有差别。

## 置信度与处置结论

最终 `decision` 直接采用 Jev 返回的 `q7_final_decision.choice`，四种结果为 `expose`、`rewrite`、`human_review`、`block`。`human_review` 是“建议人工复核”的处置标签，本工作流保存该结论后结束。

九题在同一请求中并行作答。Q7依据同一份state独立给出处置，不先读取Q1–Q6答案；Q1–Q6、risk_type与judge_score均逐项保留，便于查看模型判断是否一致。

| 输出字段 | 含义 |
| --- | --- |
| `decision` | Jev Q7的原始选择 |
| `decision_source` | 固定为 `jev_model` |
| `decision_question` | 当前九题协议为 `q7_final_decision` |
| `decision_confidence` | Q7自身置信度 |
| `confidence` | 九题最低置信度，仅为诊断统计 |
| `question_confidences` | 每题完整置信度 |
| `question_choices` | 各选择题的原始选择 |
| `escalated` | 兼容布尔标签，等于 `decision == human_review`，不表示已创建人工任务 |
| `configuration_notes` | 展示配置状态，例如 `ai_disclosure_unknown` |

置信度和严重度用于展示与评价；模型处置以Q7为准。缺字段、模型不匹配或无效响应作为运行错误单独记录，不生成处置结论。

原始响应保存在 `jev_responses.jsonl`；解析结果保存在 `jev_decisions.jsonl`；两阶段拼接的清晰展示结果为 `workflow_results.json`，每条包含推荐商品、曝光理由与 `jev_audit`。其中 `evidence_source: workflow_fact_snapshot` 表示引用文字由本地输入事实构建；它不是模型自由生成的解释。

## 审核范围与维护

这些题核验当前推荐理由的事实依据、场景相关性及曝光风险。点击率、历史曝光点击、用户是否会购买、推荐排序效果和吸引力评分不属于当前题目，历史反馈不发送给 Jev。

需要查看完整输入边界、运行参数和实测结果时，参见：

- [Jev 判断与输入契约](JEV_JUDGMENT_PROTOCOL.md)。
- [独立工作流说明](STANDALONE_WORKFLOW.md)。
- [当前工作流验证报告](TEST_REPORT_JEV_MODEL_WORKFLOW_2026-11-18.md)。
- [审核口径](JEV_REVIEW_RUBRIC.md) 与 [独立标注说明](JEV_EVALUATION_LABELING.md)。

后续修改 `build_jev_questions()` 的字段名、问题原文、题型或选项时，应同步更新本文；代码定义是实际请求的依据。

可以在项目根目录用以下只读命令查看当前完整 `questions` 对象，不会调用模型：

```bash
python3 - <<'PY'
import json
from jev_protocol import build_jev_questions
print(json.dumps(build_jev_questions(), ensure_ascii=False, indent=2))
PY
```
