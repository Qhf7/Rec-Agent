# 统一离线数据契约与 Jev 判断协议设计

## 目标

把 Rec-Agent 离线候选、Fact Bundle、MCP 数据层和 Jev 审核输入统一到同一个 canonical 数据契约，消除根目录 `item_####` 与 `data/raw/i_####` 两套数据源造成的回放断链；同时把 Jev 当前的三问扩展为可校验、可追溯的七步判断协议，为后续真实 Jev API 接入提供稳定输入输出。

本次工作的边界是“契约和离线链路先打通”。真实曝光点击埋点、在线推荐排序、人工审核平台和生产部署继续作为后续工作，不伪装成已经完成的能力。

## 现状与约束

- MCP 已以 `data/raw/` 为 canonical 数据源，商品 ID 为 `i_####`，金额字段为 `price_cents`。
- 离线候选生成器仍有代码读取根目录旧文件，使用 `item_####`、`category`、`price`，导致候选无法直接交给 MCP 和 Fact Bundle 回放。
- 现有 `exposure_reason` 是 Rec-Agent 生成的用户可见文案；Jev 只审核当前候选，不读取点击历史、CTR、订单、退款或投诉。
- `generated_reason` 继续保留为兼容字段，但必须与 `exposure_reason` 完全一致。
- 所有事实必须带数据版本和来源；无法核验的字段不能被默认为真实。

## 方案与取舍

### 方案 A：兼容适配层

保留两套旧数据，在候选进入 Fact Bundle 前做 ID 和字段转换。优点是改动较小；缺点是双数据源继续存在，数据版本、外键和回放一致性仍然容易漂移。

### 方案 B：统一 canonical 契约（采用）

以 `data/raw/` 和 `data/mock.db` 为唯一数据源，离线候选生成器、Fact Bundle、MCP 和 Jev 输入全部使用同一字段和 ID。旧候选只在迁移入口接受，迁移时必须通过标题、品牌和数字后缀校验，不能静默猜测。该方案改动较大，但可以保证 Agent → Fact Bundle → Jev → 回放使用同一份事实。

## Canonical 数据契约

### 商品

商品 ID 固定为 `i_####`，字段沿用 `data/raw/items.csv`：

`item_id`、`title`、`brand`、`category_l1`、`category_l2`、`category_l3`、`functions`、`material`、`spec`、`suit_audience`、`suit_season`、`efficacy_claims_allowed`、`qualifications`、`price_cents`、`original_price_cents`、`promo_tags`、`promo_rule_ids`、`stock`、`sales_30d`、`rating`、`return_rate_30d`、`complaint_rate_30d`、`regulated_category`、`sensitive_category`、`ad_law_notes`。

所有金额使用整数分；列表字段在工具层统一解析为数组；布尔字段在工具层统一解析为布尔值。

### 用户和场景

用户、城市气候、促销规则统一从 `data/raw/` 加载。推荐候选可以保留 `user_id` 作为追踪键，但 Jev 只接收与当前理由直接相关的最小场景摘要：城市、线级、气候区、生命周期、人群/场景标签和必要的时间场景。购物车、搜索词、点击历史、CTR、订单、退款、投诉、账户状态、设备和价格敏感度不进入 Jev 输入。

### 候选

离线和在线候选统一为：

```json
{
  "schema_version": "rec-candidate-v2",
  "data_version": "canonical-2026-06-15-v1",
  "reason_id": "r_agent_0001",
  "user_id": "u_0001",
  "item_id": "i_0001",
  "exposure_reason": "用户可见的一句话推荐理由",
  "generated_reason": "用户可见的一句话推荐理由",
  "evidence_fields": ["users.city", "items.functions"],
  "context_summary": "用于审核的最小场景摘要",
  "user_context": {},
  "item_attrs_returned": {},
  "promo_computed_in_code": {}
}
```

`item_attrs_returned` 必须来自同一版本的 canonical 商品快照，不能从旧根目录商品表拼接；`promo_computed_in_code` 只保存审核所需的促销快照，不把优惠自动写入曝光理由。

### 迁移规则

- 默认流程不再读取根目录旧 `users.csv`、`items.csv`、`promo_rules.json`。
- 旧 `item_####` 只能通过显式迁移命令转换为 `i_####`。
- 迁移必须同时校验数字后缀、标题和品牌；任一不一致就失败并报告冲突。
- 迁移后的候选统一写 `schema_version`、`data_version` 和 canonical `item_id`。
- Fact Bundle 的 provenance 统一指向 `data/raw/` 快照，禁止继续写旧根目录路径。

## Jev 输入事实包

Jev 只接收当前推荐理由的可核验事实，不接收 Agent 的隐藏推理或未来反馈。输入分为六层：

1. **追踪元数据**：`reason_id`、`item_id`、`schema_version`、`data_version`、`agent_version`、`model_version`。
2. **用户可见候选**：`exposure_reason`、`generated_reason`、`evidence_fields`。
3. **商品事实**：标题、品牌、类目、功能、材质、规格、适用人群、适用季节、资质、库存和监管类目。
4. **商业事实快照**：当前有效的价格和促销规则、适用范围、起止时间、门槛和赠品信息。
5. **确定性校验特征**：词表命中、功效支持/不支持、价格匹配、主题匹配、字段覆盖、provenance 和 verification_state。
6. **最小场景与披露**：与文案直接相关的城市/气候/人群/场景摘要，以及 AI 披露要求和当前披露标记。

禁止输入：点击历史、CTR、曝光次数、订单、退款、投诉、推荐排序分、相似用户统计、原始搜索词、购物车明细、账户标识、设备信息、人工未来标签和任何未经过事实包冻结的字段。

## Jev 七步判断协议

payload 增加 `question_schema_version: "jev-questions-v1"`，保留现有 `decision`、`risk_type`、`judge_score` 兼容解析。

| 问题 | 结构化回答 | 判断目的 |
|---|---|---|
| Q1 候选身份 | `valid / invalid / unverifiable` | 确认 reason、商品、版本和事实包是否完整一致 |
| Q2 事实支持 | `supported / partial / unsupported / unverifiable` + evidence | 逐句核验推荐理由是否能由商品/场景字段支撑 |
| Q3 表达风险 | `clean / rewriteable / blocking` + risk type | 检查绝对化、功效/医疗、误导性或披露缺失表达 |
| Q4 商业准确性 | `verified / mismatch / not_mentioned / unverifiable` | 核验价格、折扣、满减、赠品和有效期 |
| Q5 场景相关性 | `relevant / off_topic / unverifiable` | 判断用户场景与商品事实是否相关，避免无依据个性化 |
| Q6 安全门禁 | `pass / human_review / fail` + escalation reason | 处理缺字段、冲突、敏感类目和低置信度情况 |
| Q7 最终处置 | `expose / rewrite / human_review / block` + score/confidence/evidence | 输出可执行的最终审核结果 |

处置优先级固定为：不可验证或事实冲突进入 `human_review`；无法安全修复的硬风险进入 `block`；可以机械修复的表达或披露问题进入 `rewrite`；事实完整、相关且无硬风险才允许 `expose`。

## 兼容与验收

- 旧版只返回三问的 Jev 响应仍可解析；缺少 Q1–Q6 时由协议适配层标记为兼容响应，不把缺失问题伪装成完整七问。
- 新 payload 必须通过严格 Schema 校验，证据引用只能指向事实包白名单路径。
- 离线候选经过 canonical loader 后，必须可以直接调用 MCP `get_item(i_####)` 找回同一商品。
- Fact Bundle、候选和 Jev payload 的 `item_id`、`reason_id`、`data_version` 必须保持一致。
- Jev payload 不得出现点击历史、CTR、订单、退款、投诉和排序分字段。
- 迁移冲突、缺商品、版本不一致和证据路径非法必须失败并给出明确错误。
- 新增测试覆盖 canonical 回放、旧候选迁移、七问结构、禁传字段、旧三问兼容和端到端离线链路。

## 非目标

- 本阶段不接入真实 Jev API 凭据，不声称已经完成线上审核。
- 本阶段不实现曝光点击 SDK、事件流、人工审核平台、在线排序学习或生产部署。
- 本阶段不把点击反馈、订单和投诉等未来结果泄漏给 Jev。
