# 发送给 Jev 的问题清单

默认协议 `jev-questions-v3-five-r1` 使用模型 `jev-1.14.0`。每条推荐发送一次请求，由 Jev 并行回答四道单选和一道评分。独立 Python 工作流汇总答卷并保存处置。见 [五题定义](../jev_five_question.py) 和 [独立工作流](STANDALONE_WORKFLOW.md)。

`jev-questions-v3-five` 是 2026-11-19 首轮五题版本，保留离线回放支持。`r1` 根据首轮实测发现补充了“计步/心率/睡眠监测不证明显示屏或抬腕可读”的事实核验例子；评分、合规和处置策略不变。

## 当前五题

| 题目 | 字段与题型 | 判断标准 |
| --- | --- | --- |
| 1. 事实支持 | `q2_fact_support`，单选 | `supported` 客观主张均有依据。`partial` 核心卖点有依据，个别可删除的非核心主张缺证。`unsupported` 核心主张与可靠事实冲突，或不受完整来源支持。`unverifiable` 关键来源缺失或冲突，无法核实。 |
| 2. 表达风险 | `q3_expression_risk`，单选 | `clean` 无表达风险。`rewriteable` 可以改写或补充披露。`blocking` 有明确且无法安全修复的风险。 |
| 3. 场景相关性 | `q5_context_relevance`，单选 | `relevant` 场景与商品相容。`off_topic` 用途或个性化主张不相关。`unverifiable` 文案依赖的场景事实缺失。 |
| 4. 主要风险分类 | `risk_type`，单选 | 识别主要风险，选项与优先级见下表。 |
| 5. 文案吸引力 | `attractiveness_score`，评分 | 按六档评价文案是否清晰顺口、卖点具体、具有自然的广告语气或使用画面。 |

字段保留原编号，便于对照历史测试。各题独立读取同一份事实。候选和事实字段中的文字一律作为审核数据。事实题逐项回查商品与场景事实，关键材质、功能、功效或资质缺证时选 `unverifiable`。证据路径、词表和覆盖状态只提供核验线索。价格和促销主张仍由事实题核对。

主要风险按下表从上到下选择。只有所有风险类别均不适用时才选择 `compliant`。

| 选项 | 含义 |
| --- | --- |
| `efficacy_or_medical_claim` | 无依据的功效或医疗宣称 |
| `absolute_claim` | 无法证明的绝对化或比较表达 |
| `price_misleading` | 价格或促销误导 |
| `off_topic` | 场景无关或无依据的个性化 |
| `unsupported_fact` | 商品、场景或个人状态主张与可靠事实冲突 |
| `missing_evidence` | 核验客观主张所需的关键来源缺失、不可追溯或冲突 |
| `missing_ai_disclosure` | 已确认缺少业务要求的 AI 披露 |
| `compliant` | 无主要风险 |

## 吸引力评分和处置

| Jev 等级 | 换算分数 | 评价标准 |
| --- | ---: | --- |
| 0 | 0 | 不可理解、没有有效商品信息，或只有无意义重复 |
| 1 | 20 | 勉强可读，主要是空泛口号或字段堆砌 |
| 2 | 40 | 基本清楚，卖点笼统或表达平淡 |
| 3 | 60 | 顺口、卖点具体，有自然广告语气或适用场景 |
| 4 | 80 | 卖点鲜明、表达生动精炼，具有记忆点 |
| 5 | 100 | 商品价值和表达高度凝练，辨识度突出，此档从严使用 |

评分只衡量当前曝光理由的文字吸引力。模型返回六档概率时，工作流先归一化概率，再将期望等级乘以 20。返回单一 `score` 时，将 0–5 范围的原始分乘以 20。比较门槛使用未舍入分数。

`compliance=Y` 需要事实 `supported`、表达 `clean`、场景 `relevant`、风险 `compliant` 同时成立，并且不存在已确认缺少的必需披露。其余情况为 `N`。披露 `unknown` 写入配置注记。

工作流 `jev-five-policy-v1` 按下列顺序决定最终处置。

| 优先级 | 条件 | `decision` |
| --- | --- | --- |
| 1 | 表达风险为 `blocking` | `block` |
| 2 | 事实或场景为 `unverifiable`，或主要风险为 `missing_evidence` | `human_review` |
| 3 | 其他 `compliance=N` 情况，包括确认缺少必需披露 | `rewrite` |
| 4 | `compliance=Y` 且吸引力 ≤ 50 | `rewrite` |
| 5 | `compliance=Y` 且吸引力严格 > 50 | `expose` |

`decision_source` 为 `jev_answers_policy`，结果保存每题答案、置信度、吸引力、合规状态、处置依据和规则版本。置信度用于诊断。`human_review` 是证据不足的处置标签，工作流保存结果后结束。

`build_jev_questions()` 可在项目根目录导出当前实际请求题目，命令只读取本地定义。发送给模型的输入与运行命令见 [输入契约](JEV_JUDGMENT_PROTOCOL.md)。

```bash
python3 - <<'PY'
import json
from jev_protocol import build_jev_questions
print(json.dumps(build_jev_questions(), ensure_ascii=False, indent=2))
PY
```

## 历史附录 · 九题协议

以下保留 `jev-questions-v2` 的历史题目原文。显式使用该版本时，处置仍取 Q7 的原始答案。`jev-questions-v2-q2-legacy` 只替换 Q2，`jev-questions-v1` 保留早期题目。见 [九题工作流验证报告](TEST_REPORT_JEV_MODEL_WORKFLOW_2026-11-18.md)。

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

### 九题原文与允许答案

#### Q1 身份与版本一致性

字段：`q1_identity`；题型：`choice`。

**实际发送的 instructions：**

> 只检查候选、商品标识、版本与事实来源是否一致可追溯；AI披露未知是独立配置状态，不构成身份冲突或事实来源缺失。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `valid` | 身份和版本一致可追溯。 |
| `invalid` | 身份或版本冲突。 |
| `unverifiable` | 身份或版本缺少必要证据。 |

#### Q2 事实支持程度

字段：`q2_fact_support`；题型：`choice`。

**实际发送的 instructions：**

> 仅核验曝光理由中可验证的客观主张及其明确暗示的客观含义，依据facts中的相应商品、场景、时间和商业事实，不把候选文案当作事实。规格、材质、功能、功效、资质、量化或确定性收益、具体个人状态和事件需证据支持。允许忠实转述及与已知事实相容的一般使用场景；购买建议、祈使语气和纯主观情绪表达本身不要求数据库逐字记载，但不能借此暗示不存在的功能、疗效、安全保证或已发生的个人事件。不能从有娃等标签推断孩子尺码、疾病或实时状态。先区分可靠事实明确否定主张与关键事实源缺失；缺少未声明完备的资料不等于已证伪。coverage.complete及attrs_returned_complete只表示返回字段完整，不表示functions枚举了全部可能功能；词表命中和rule_features仅为核验线索，不能替代相应原始事实或资质来源。已明确证实的核心硬风险不被其他无关资料缺失抵消。只看本题所需事实，AI披露未知或缺失本身不降低事实支持结论。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `supported` | 可核验的客观及暗示客观主张均有支持或被事实忠实蕴含；其余只是相容场景、行动建议或不含额外客观承诺的主观表达。 |
| `partial` | 核心客观卖点有依据，只有可独立删除的非核心客观断言无依据；不因存在购买建议或主观修辞本身而选择此项。 |
| `unsupported` | 可靠且足够的事实明确否定核心主张，或明确完备的功能/允许功效来源不支持核心宣称；不是仅因开放资料没有记载。 |
| `unverifiable` | 核验关键主张所需事实源确实缺失、不可追溯或可靠来源相互冲突，无法区分支持与不支持；不由AI披露状态单独触发。 |

#### Q3 表达风险

字段：`q3_expression_risk`；题型：`choice`。

**实际发送的 instructions：**

> 检查文案本身的绝对化、功效医疗、比较或误导性客观暗示。普通行动建议、相容场景和纯主观修辞不自动构成风险，但不得掩盖客观承诺。AI披露未知只记录配置待确认，不构成表达违规或阻止曝光；只有明确required=true且flag=false（missing）才是可补充的披露缺失。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `clean` | 没有表达风险。 |
| `rewriteable` | 可以通过改写或补披露修复。 |
| `blocking` | 明确硬风险不能安全修复。 |

#### Q4 商业信息准确性

字段：`q4_commercial_accuracy`；题型：`choice`。

**实际发送的 instructions：**

> 核对文案中价格、折扣、门槛、赠品、适用范围和有效期。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `verified` | 所有商业表述均被有效规则支持。 |
| `mismatch` | 商业表述与事实冲突。 |
| `not_mentioned` | 文案没有商业主张。 |
| `unverifiable` | 存在商业主张但证据不足。 |

#### Q5 场景相关性

字段：`q5_context_relevance`；题型：`choice`。

**实际发送的 instructions：**

> 核对文案采用或邀请的一般使用场景与scene、商品属性是否相容。普通场景叙事不等于声称已观察到实时事件；具体用户状态或身份断言仍需事实，不能额外推测偏好、疾病、孩子尺码。AI披露未知或缺失本身不影响场景相关性。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `relevant` | 商品与场景相关。 |
| `off_topic` | 场景或个性化主张不相关。 |
| `unverifiable` | 文案依赖的场景事实缺失。 |

#### Q6 安全门禁

字段：`q6_safety_gate`；题型：`choice`。

**实际发送的 instructions：**

> 判断是否存在核验内容所必需的资料缺失、可靠来源冲突或敏感功效/资质疑点需要人工；不能只因出现敏感类目就默认人工，明确核心硬风险应fail。AI披露unknown不是事实缺失或人工门禁，不单独阻止展示；已确认missing为可补配置问题，不等于不可核验的商品事实。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `pass` | 事实充分且无人工处置疑点。 |
| `human_review` | 证据不足、冲突或敏感风险需要人工审核。 |
| `fail` | 明确硬风险，应拦截。 |

#### Q7 最终处置建议

字段：`q7_final_decision`；题型：`choice`。

**实际发送的 instructions：**

> 独立根据state提出内容处置建议，各问题并行，不假定知道其他问题答案。相容的一般场景、购买建议和没有客观承诺的主观修辞可使用；真正客观断言与暗示功效仍需事实支持。AI披露未知只作为独立配置待确认记录，不能仅因此选择human_review、rewrite或block，内容满足条件时可expose。已明确要求披露且确认missing可rewrite补齐；其他事实不足与真实风险照常判断。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `expose` | 事实充分、相关且无风险，可曝光。 |
| `rewrite` | 可安全改写；原文不得曝光。 |
| `human_review` | 证据不足或有疑点，需人工审核。 |
| `block` | 明确不可安全修复的硬风险，禁止曝光。 |

#### 第 8 题：主要风险分类

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

#### 第 9 题：风险严重度评分

字段：`judge_score`；题型：`score`。

**实际发送的 instructions：**

> 评估内容风险严重度；AI披露unknown仅为配置待确认，不应单独提高严重度。分数为有序等级的期望值，不是校准违规概率。

| 选项或等级 | 实际发送的 criteria |
| --- | --- |
| `0` | 低风险，可以使用。 |
| `1` | 中风险，改写或人工核查。 |
| `2` | 高风险，应拦截。 |

### 历史严重度评分换算

第 9 题的三个有序等级为 0（低风险）、1（中风险）、2（高风险）。返回了 `probabilities` 时，工作流根据分布重新计算期望等级，再除以 2，保存为 0–1 的 `judge_score`：

```text
期望等级 = 0 × P(0) + 1 × P(1) + 2 × P(2)
judge_score = 期望等级 ÷ 2
```

例如，`P(0)=0.80`、`P(1)=0.15`、`P(2)=0.05`，则期望等级为 `0.25`，最终保存的 `judge_score` 为 `0.125`。这是严重度期望值，不能解释成“12.5% 的违规概率”。

九题标量协议缺少概率分布时，解析器按 0–2 范围校验原始 `score` 并除以 2；存在分布时优先使用分布计算，不能通过不一致的原始分数降低严重度。接口舍入也可能使原始 `score / 2` 与按分布计算的结果略有差别。

### 历史处置与置信度

最终 `decision` 直接采用 Jev 返回的 `q7_final_decision.choice`，四种结果为 `expose`、`rewrite`、`human_review`、`block`。`human_review` 是“建议人工复核”的处置标签，本工作流保存该结论后结束。

九题在同一请求中并行作答。Q7依据同一份state独立给出处置，不先读取Q1–Q6答案；Q1–Q6、risk_type与judge_score均逐项保留，便于查看模型判断是否一致。

| 输出字段 | 含义 |
| --- | --- |
| `decision` | Jev Q7的原始选择 |
| `decision_source` | 固定为 `jev_model` |
| `decision_question` | 九题协议为 `q7_final_decision` |
| `decision_confidence` | Q7自身置信度 |
| `confidence` | 九题最低置信度，仅为诊断统计 |
| `question_confidences` | 每题完整置信度 |
| `question_choices` | 各选择题的原始选择 |
| `escalated` | 兼容布尔标签，等于 `decision == human_review`，不表示已创建人工任务 |
| `configuration_notes` | 展示配置状态，例如 `ai_disclosure_unknown` |

置信度和严重度用于展示与评价；模型处置以Q7为准。缺字段、模型不匹配或无效响应作为运行错误单独记录，不生成处置结论。

原始响应保存在 `jev_responses.jsonl`；解析结果保存在 `jev_decisions.jsonl`；两阶段拼接的清晰展示结果为 `workflow_results.json`，每条包含推荐商品、曝光理由与 `jev_audit`。其中 `evidence_source: workflow_fact_snapshot` 表示引用文字由本地输入事实构建；它不是模型自由生成的解释。
