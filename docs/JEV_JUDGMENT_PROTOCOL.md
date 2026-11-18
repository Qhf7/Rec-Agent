# Jev 判断问题与输入契约

当前实现把推荐生成和曝光审核连接为独立工作流。DeepSeek Harness/Rec-Agent 输出推荐 JSON 后结束；Harness 外的 `scripts/run_recommendation_workflow.py` 接收 JSON 或 canonical JSONL，生成事实包并在显式 `--live` 时调用 Jev。

## 一、供 Jev 判断的问题

| 逻辑问题 | 核验重点 | 允许回答 | 例子 |
| --- | --- | --- | --- |
| Q1 身份一致性 | 理由 ID、商品 ID、数据版本、事实来源是否一致 | valid / invalid / unverifiable | 推荐 i_0001，事实却来自另一商品，不能放行 |
| Q2 事实支持 | 理由中每个主张是否被商品/场景事实支持 | supported / partial / unsupported / unverifiable | 收纳盒只有折叠功能，不能宣称治疗鼻炎 |
| Q3 表达风险 | 绝对化、功效医疗、商业误导、披露及跑题 | clean / rewriteable / blocking | 绝对化措辞可建议改写；明确无依据医疗宣称应拦截 |
| Q4 商业准确性 | 价格、折扣、门槛、赠品、适用范围和起止时间 | verified / mismatch / not_mentioned / unverifiable | 商品在活动范围内不代表购物篮已满足满减门槛 |
| Q5 场景相关性 | 理由采用的场景、身份与商品是否匹配 | relevant / off_topic / unverifiable | 城市和标签不能支持模型额外推测用户身份 |
| Q6 安全门禁 | 缺失、冲突、敏感类目、资质及人工审核需求 | pass / human_review / fail | 关键功效资料缺失先转人工，不猜测为真 |
| Q7 处置建议 | 独立根据同一份事实提出曝光建议 | expose / rewrite / human_review / block | 改写/人工/拦截均不允许原文直接曝光 |

另有两个 API 问题：`risk_type` 选择六类主要风险，`judge_score` 评估三级风险严重度。总计八个 Choice、一个 Score。正式定义见 `jev_protocol.build_jev_questions()`。

这些问题在一次请求中并行判断。Q7 只是处置建议，工作流再结合 Q1–Q6、置信度和确定性规则决定最终结果；Q7 不能跳过其它门禁。

## 二、交给 Jev 的信息

| 输入层 | 实际字段/内容 | 来源与用途 |
| --- | --- | --- |
| 候选 | reason_id、item_id、exposure_reason、generated_reason、evidence_fields、schema/data version | 固定本次审核文本；两份理由必须完全相同 |
| 商品 | 标题、品牌、三级类目、功能、材质、规格、人群、季节、允许功效、资质、价格、库存、监管与风险说明 | 只来自同版本 data/raw/items.csv；不包含销售量、评分、退货或投诉率 |
| 商业快照 | promo_id、规则类型、适用范围、有效期、门槛、减额、折扣和赠品 | data/raw/promo_rules.json；按快照日期计算，不能把单品适用性当作购物篮满足门槛 |
| 最小场景 | 城市、城市层级、气候区、生命周期、场景标签、活跃时段 | data/raw/users.csv 的受限字段 |
| 气候与时间 | 规范城市气候区、梅雨月份、场景日期、快照时间与时区 | data/raw/city_climate.json + 冻结 snapshot_at；不当作实时天气 |
| 校验与来源 | 词表命中、规则特征、字段覆盖、verification_state、provenance、AI 披露状态 | 工作流计算并冻结；与模型生成文案分开 |
| 追踪 | reason_id、item_id、候选/事实/问题/数据版本、agent/model version | 用于追溯与回放；Jev 不接收 user_id |

不传给 Jev：推荐点击历史、CTR、曝光统计、原始搜索词、购物车明细、订单、退款、投诉、账户标识、设备、排序分、相似用户统计、人工 gold 标签、模拟潜在结果。`context_summary` 可留在本地候选供排查，不把含行为细节的自由文本直接当成 Jev 事实。

所有字段同时校验键与值的类型，数组逐项检查。不能借助披露标记、功能列表或其它白名单字段嵌入未知对象或未来结果。证据路径还必须指向实际发送且有值的字段。

## 三、代码如何汇总

1. 事实无法核验、存在冲突、Q1 身份异常、Q6 需要人工、模型已升级或任一关键回答置信度低于 0.7：`human_review`。
2. 明确的无依据核心主张、不可修复表达、商业事实冲突或 Q6 fail：`block`。
3. 可修复的部分支持、绝对化、跑题或缺少披露：`rewrite`；已拦截的结果保持拦截。
4. 只有建议为 expose、风险为 compliant、事实通过且各门禁通过时才允许 `expose`。曝光建议与中高风险分数冲突则转人工。规则未命中不能把模型拦截改成曝光。

Score 的等级为 0/1/2，从返回概率分布计算期望等级后除以 2。它表示风险严重度，不是经过真实业务结果校准的违规概率。模型置信度和风险分数用途不同，分别用于审核可靠性和风险程度。

`evidence` 默认由工作流呈现输入事实、词表命中和触发的门禁，`evidence_source=workflow_fact_snapshot`。该值不声称是 Jev 自由生成的逐句解释。审核结果另存，不回填到推荐 JSON。

## 四、数据统一与回放

唯一规范源为 `data/raw/`。商品 ID 为 `i_####`，金额为整数分，候选契约 `rec-candidate-v2`，事实包 `fact-bundle-v2`，数据版本 `canonical-2026-06-15-v1`。MCP、离线生成器和工作流共享加载器。

旧 `item_####` 通过 `scripts/migrate_legacy_candidates.py` 显式迁移，必须同时核对数字后缀、标题和品牌，不能按后缀猜测同一商品。冲突中断且不会覆盖已有输出。canonical 候选禁止快照字段漂移或伪造功效/促销。

Harness 导出会创建本次 canonical 快照；已有 JSONL 回放保留原快照子集、原时间和原查询记录，缺字段不会补成已核验。模拟场景基准为 2026-06-15，与执行当天不同。

## 五、运行与验证边界

```bash
python3 scripts/run_recommendation_workflow.py \
  --input examples/harness_recommendations.json \
  --output-dir /tmp/rec-agent-protocol-prepare
```

默认只写候选、事实包、请求和报告，`network_calls=0`。实际运行模型需设置 `MODELGO_API_KEY` 并显式增加 `--live`，披露状态按真实展示配置填写。

本轮已运行 139 项自动化测试、数据硬校验、340 条合成候选请求构造，以及 300 条独立 CLI 批量准备。真实新版 API 冒烟、真实曝光点击采集、人工审核平台和生产部署尚未在本轮完成。合成标签一致性不代表 Jev 的真实效果。

完整命令、披露状态与产物说明见 [独立工作流](STANDALONE_WORKFLOW.md)。
