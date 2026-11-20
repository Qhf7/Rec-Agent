# Harness → Jev 全链路实测

日期：2026-11-20

## 测试配置

- 在 DeepSeek Harness 新建会话并选择 Rec-Agent，以合成测试用户 `u_0199` 发起新一轮推荐。
- Harness 界面显示模型路由 `deepseek-v4.1-flash-1017`、Max 推理；用时约 1 分 52 秒，生成 3 条候选。
- Harness 最终回答为一个合法 JSON 对象，推荐理由字段完整，`exposure_reason` 与 `generated_reason` 一致；理由均不超过 20 字，未在理由中写具体数量参数。
- 独立 Python 工作流按规范数据重建事实，再实时调用 Jev `jev-1.14.0` 三次。当前协议为 `jev-questions-v3-five-r1`，汇总规则为 `jev-five-policy-v1`。
- 业务快照日期为 `2026-06-15`；AI 披露状态为 `unknown`，作为配置注记保留，不单独判为不合规。
- 3/3 个 Jev 响应解析成功，`error_count=0`。测试只覆盖本轮 3 条候选，不能据此推算模型准确率。

## 结果

| 商品 | Harness 曝光理由 | 事实支持 | 表达 | 场景 | 风险类别 | 吸引力分 | 合规 | 最低题目置信度 | 最终处置 |
| --- | --- | --- | --- | --- | --- | ---: | --- | ---: | --- |
| 智能手环 `i_0111` | 心率计步随手看，运动更有数 | supported | clean | relevant | compliant | 51.0 | Y | 0.27 | expose |
| 机械键盘 `i_0119` | 热插拔换轴，打字随心安排 | supported | clean | relevant | compliant | 55.8 | Y | 0.62 | expose |
| 儿童短袖 `i_0145` | 纯棉亲肤透气，夏日穿着自在 | supported | clean | relevant | compliant | 53.4 | Y | 0.75 | expose |

吸引力分是 Jev 0–5 评分期望值乘以 20。最终处置不由 Jev 单独回答，而由工作流按四道单选和评分汇总：表达为 `blocking` 时 `block`；事实或场景不可核验，或风险为 `missing_evidence` 时 `human_review`；其他合规失败时 `rewrite`；合规但吸引力不严格大于 50 时 `rewrite`；只有合规且吸引力严格大于 50 才 `expose`。本轮三条单选均为合规，评分均高于 50，因此三条均曝光。

## 结果分析

手环商品事实列有计步、心率和睡眠监测，但没有显示屏或抬腕可读信息。Jev 将“心率计步随手看”判为 `supported`，该题置信度为 0.27；Q2 概率分布中 `supported` 为 0.45、`partial` 为 0.40、`unsupported` 为 0.02、`unverifiable` 为 0.13。风险分类的 `missing_evidence` 概率为 0.27，但最终单选为 `compliant`。当前规则不使用题目置信度或未选中的概率类别作门禁，所以该候选最终仍为 `expose`。这显示“随手看”可能暗示查看界面的边界需要继续校准。

键盘理由中的热插拔换轴与商品标题及属性一致；短袖理由中的纯棉、亲肤、透气和夏季场景均有商品事实支持。本轮没有独立人工金标，每条只调用 Jev 一次，也未评估重复调用稳定性。吸引力分衡量当前文案，不是点击率预测；不能据此声称准确率提升或线上效果。

本轮原始 Harness 导出、事实快照、请求、响应和解析结果保存在本机忽略目录 `runs/2026-11-20-harness-jev-live/`，不会提交到 GitHub。API 凭据未写入报告或仓库。
