# Jev 审核题目

每条推荐对应一次 Jev 请求，包含一道风险单选题和一道吸引力评分题。默认模型为 `jev-1.14.0`，协议为 `jev-questions-v4-two`。

## 风险分型

字段：`risk_type` · 类型：`choice` · 六选一。

| 选项 | 判断标准 |
| --- | --- |
| `compliant` | 其余五类风险均不适用。 |
| `absolute_claim` | 存在无法证明的绝对化、保证性或比较优势表达。 |
| `efficacy_or_medical_claim` | 存在无可靠依据的功效、疗效或医疗宣称，包括暗示的效果承诺。 |
| `price_misleading` | 价格、折扣、门槛、赠品、范围或有效期与可信规则不符，或缺少必要支持。 |
| `missing_ai_disclosure` | 业务要求 AI 披露，且已确认缺失：`required=true`、`flag=false`。 |
| `off_topic` | 场景与商品不相容，或包含无事实支持的具体个人状态、身份及个性化断言。 |

模型依据商品、促销、场景和披露事实核验文案。一般使用场景、购买建议及主观广告修辞可以使用，客观效果和具体个人状态仍需事实支持。披露状态为 `unknown` 表示待确认。

多风险并存时，主风险优先级为：功效或医疗 → 绝对化 → 价格误导 → 场景无关 → 披露缺失。`compliant` 表示上述分类范围内无适用风险，审核范围见[输入契约](JEV_JUDGMENT_PROTOCOL.md)。

## 文案吸引力

字段：`attractiveness_score` · 类型：`score` · 业务分数：**1–100**。

评价清晰度、卖点具体程度、广告语气、使用画面、精炼度和记忆点。吸引力与合规分别判断；分数用于评价当前文案表达。

| 分数 | 评价参考 |
| --- | --- |
| 1–20 | 难以理解、有效商品信息少，或重复过多。 |
| 21–40 | 基本可读，但卖点笼统、表达生硬。 |
| 41–50 | 信息清楚，表达平淡。 |
| 51–70 | 卖点具体、语言自然，有适用的使用画面。 |
| 71–90 | 生动精炼、商品价值鲜明且有记忆点。 |
| 91–100 | 高度凝练、辨识度突出，从严使用。 |

### 评分换算

SystemOne 接口最多支持 10 个评分等级。模型返回的等级索引 `0…9` 对应业务锚点 `1、12、23、34、45、56、67、78、89、100`。

```text
有等级概率：业务分 = 1 + 11 × Σ(k × p[k])，k = 0…9
仅有等级分：业务分 = 1 + 11 × 等级索引
```

概率先归一化，业务分可带小数，处置门槛使用未舍入值。该分数来自有序等级映射，含义是文本吸引力，不代表点击率或购买率。

## 合规与处置

汇总规则版本：`jev-two-policy-v1`。

| Jev 风险结果 | 吸引力分 | `compliance` | `decision` |
| --- | --- | --- | --- |
| `compliant` | > 50 | `Y` | `expose` |
| `compliant` | ≤ 50 | `Y` | `rewrite` |
| 其余五类 | 任意有效分 | `N` | `rewrite` |

合规状态和最终处置由两题答案汇总，恰好 50 分时为 `rewrite`。置信度和覆盖状态保留为诊断信息；披露风险由模型在风险题中判断。`rewrite` 表示未达到曝光条件，后续改写由调用方处理。

## 查看题目定义

题目由 [`jev_two_question.py`](../jev_two_question.py) 定义。可在项目根目录导出实际请求中的题目：

```bash
python3 - <<'PYTHON'
import json
from jev_protocol import build_jev_questions
print(json.dumps(build_jev_questions(), ensure_ascii=False, indent=2))
PYTHON
```

[输入与输出契约](JEV_JUDGMENT_PROTOCOL.md) · [工作流使用说明](STANDALONE_WORKFLOW.md)
