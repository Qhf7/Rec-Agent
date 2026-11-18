# Jev 边界样本与离线人工标注

本项目提供40条专门构造的审核测试文案，覆盖10个商品组：24条开发评估样本、16条留出样本。样本文件沿用 `calibration` / `holdout` 集合标识；商品组和商品ID不跨集合，留出集合也不含先前六条DS推荐的商品。

这些材料用于可选的离线模型质量评估。日常工作流直接保存 Jev 的处置结论；其中 `human_review` 是结果标签，实际人工复核不在当前工作流内。

样本文案并非新的DS生成结果，也不是已展示给真实用户的商品。属性读取同版本 `data/raw/`；缺失资料测试只删除观察到的字段，保持可复现的事实快照。

## 标签性质与样本冻结

`tests/fixtures/jev_review_cases.json` 中的 `provisional_q2`、`provisional_decision` 和解释标为 `provisional_agent_review`，是暂定编辑判断，用于观察模型行为变化。它们不代表独立人工金标，不能据此报告真实审核准确率。

先冻结样本文件及哈希，再发起新旧Q2对照。模型结果不应反过来修改留出样本的期望答案；歧义样本经独立标注和仲裁后形成新版本。

## 准备盲标材料

在项目根目录执行，网络调用为0：

```bash
python3 scripts/build_jev_review_evaluation.py \
  --output-dir runs/jev-review-evaluation-001
```

| 文件 | 内容 |
| --- | --- |
| `candidates.jsonl` | 规范候选、商品/场景快照及保留的缺失，不含期望标签 |
| `manifest.json` | 冻结样本、分组、集合、标签来源、原始文件哈希及统计 |
| `human_annotation_template.csv` | 盲标表，仅提供文案及实际来源事实，标签为空 |

盲标表不包含期望答案、测试类别、模型回答、词表命中或本地规则判断。`facts_json` 保留商品、场景、时间、优惠、披露及覆盖状态。分组和集合信息在独立manifest中维护，不发送给Jev。

`candidate_from_case(case, ai_disclosure="unknown")` 生成稳定的reason_id，可对齐旧题、新题、重复调用及披露控制。它仅读取候选身份、文字、证据路径和明确省略字段，标签与编辑解释不进入Jev输入。

## 可选的独立人工标注

两位标注者按 [审核口径](JEV_REVIEW_RUBRIC.md) 分别阅读同一份文案与事实。可各发一份独立副本，完成后合并，避免互相看到答案；模型输出和暂定标签不提供给标注者。

- `reviewer1_id` / `reviewer2_id`：两位不同的真实标注者标识。
- `reviewer1_q2` / `reviewer2_q2`：supported、partial、unsupported、unverifiable。
- `reviewer1_decision` / `reviewer2_decision`：expose、rewrite、human_review、block。

完成独立判断后，由仲裁者填写 `adjudicator_id`、`adjudicated_q2`、`adjudicated_decision`，并将 `label_source` 设为 `human_adjudicated`。分歧应按具体主张与证据边界解决，不直接采用模型回答作为金标。

CSV中的case_id、item_id、exposure_reason和facts_json保持不变。`load_adjudicated_labels(path, cases)` 校验标签完整性、不同标注者和事实一致性；空模板保留为空，半填、重复标注者、暂定标签或文案漂移会被拒绝。格式检查不能技术上证明标注者独立性，执行者仍应如实记录来源。

## 评估解释

有独立人工金标后，可分别报告：人工block而模型expose的比例、模型expose集合中的人工block占比、正常文案误改写/误拦截、`human_review`标签占比、逐题混淆矩阵和重复一致性。应明确每项分母以及独立样本数，重复调用不增加独立样本数量。

`human_review`比例统计的是模型选择该标签的频率，不表示创建或完成了人工复核任务。开发集和留出集分开报告；专门构造的风险样本占比不代表生产分布。40条样本主要用于小规模回归与初步对照，不能稳定估计很低的业务错误率。

## 回放冻结模型结果

```bash
python3 scripts/replay_jev_model_decisions.py \
  --comparison-dir runs/2026-11-18-q2-v2-live \
  --output-dir runs/jev-model-replay-001
```

回放只解析保存的原始响应，网络调用为0，处置结论逐条来自Jev原始Q7。新的结果写到独立目录，保留历史运行记录。冻结输入的完整facts哈希用于核对事实、规则特征与词表命中，避免回放期间输入漂移。

回放无需人工标签；人工标注可在模型质量分析时另行关联。当前工作流验证见 [测试报告](TEST_REPORT_JEV_MODEL_WORKFLOW_2026-11-18.md)。
