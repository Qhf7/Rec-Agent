# Jev v2 受控对照与校准准备报告

> 历史执行记录：以下统计保留当次运行的汇总行为。当前工作流直接采用 Jev Q7 处置，见 [当前工作流验证报告](TEST_REPORT_JEV_MODEL_WORKFLOW_2026-11-18.md)。

日期：2026-11-18。当前默认模型 `jev-1.14.0`，接口 `https://api.modelgo.ai/v1/systemone`，默认九题最低置信度门槛 **0.7 保持不变**。本轮完成172次真实审核调用，全部返回且成功解析。没有独立人工金标，尚未选出或部署新门槛。

## 1. 实现顺序与当前状态

| 顺序 | 工作 | 状态 |
| --- | --- | --- |
| 1 | 区分客观事实、一般场景、主观表达、具体个人状态和暗示功效，明确 Q2 选项边界 | 已实现，见 [审核口径](JEV_REVIEW_RUBRIC.md) |
| 2 | 商品事实状态与披露状态分离，unknown 只记录独立配置原因 | 已实现并验证可曝光 |
| 3 | 固定商品、文案、模型和其他八题，运行新旧 Q2 对照及更多边界样本 | 40条×2版本×2重复，已完成160次；另有12次回归/披露控制 |
| 4 | 独立人工标注、风险指标和留出验证后选择汇总门槛 | 工具和40行盲标模板已完成；等待人工标注，阈值未改变 |

DS Harness 仍只生成推荐。此次直接复用已保存的六条桌面端推荐作为回归输入，没有重新启动 DS 生成，也没有把 Jev 接入 Harness 自动工具链。扩展40条是专门构造的边界用例，数据源是 mock 商品/场景快照，并非真实用户曝光点击。

## 2. 审核口径和输出变化

Q2仅核验客观主张及明确暗示的客观含义。规格、材质、功效、资质、量化收益和具体个人事件需要证据；相容的一般场景、邀请或行动建议、没有额外客观承诺的主观感受无需数据库逐字记载。`partial` 只表示核心卖点有依据而非核心客观断言可删除；`unsupported` 区别于关键来源缺失的 `unverifiable`。开放功能列表未记载，不自动证明某功能不存在。

`verification_state` 仅依赖事实来源与覆盖。披露单独保留 visible/missing/unknown；unknown 写入 `configuration_notes: ["ai_disclosure_unknown"]`，不会单独阻止展示、降低Q2或触发人工。确认缺少必需披露（flag=false）仍需要补齐。最终结果增加 `gate_reasons`、每题置信度、问题选择、策略版本和门槛，便于区分配置原因、模型建议与本地门禁。

Q4原文、选项和汇总处理未更改。原六条都没有价格或促销承诺，所以新版仍为 `not_mentioned`；它不表示缺少商品事实。

## 3. 对照设计与冻结产物

- A：`jev-questions-v2-q2-legacy`，其他八题采用新披露口径，只有Q2保留冻结v1原文。
- B：`jev-questions-v2`，当前默认题目。
- 两组商品、候选文案、事实包、场景、模型相同，其他八题逐项一致；请求前自动核对。问题版本元数据与state中的Q2定义随组变化。
- 40条/10个商品组：calibration 24条、holdout 16条，按商品分组隔离，留出商品不含原六条。
- 每条每组调用两次，合计160次；重复用于观察波动，不把80次调用视为80条独立样本。
- 原六条回归6次，3条客观文案增加visible/missing各一次共6次；它们不参与门槛选择。
- 冻结fixture SHA256：`c4712ba613aff975653aab996b8720643f1c3d2eaab02543e9550abd17299018`。
- 场景数据日期为2026-06-15，执行日期为2026-11-18；不是实时天气或当前促销。

| 调用组 | 计划 | 原始响应 | 成功解析 | 错误 |
| --- | ---: | ---: | ---: | ---: |
| 新旧Q2对照 | 160 | 160 | 160 | 0 |
| 原六条回归 | 6 | 6 | 6 | 0 |
| 披露控制 | 6 | 6 | 6 | 0 |
| 合计 | 172 | 172 | 172 | 0 |

本次并发3，总调用阶段约69.1秒。响应先于解析落盘；请求不含点击历史、CTR、模型结果或暂定/人工标签。成功解析只证明协议有效，不证明答案正确。

产物：`runs/2026-11-18-q2-v2-live/manifest.json`、`runs/2026-11-18-q2-v2-live/requests.jsonl`、`runs/2026-11-18-q2-v2-live/responses.jsonl`、`runs/2026-11-18-q2-v2-live/decisions.jsonl`、`runs/2026-11-18-q2-v2-live/summary.json`、`runs/2026-11-18-q2-v2-live/comparison_results.csv`。这些运行产物保存在本地 `runs/`，按仓库设置不纳入Git。

## 4. 新旧 Q2 的实际差异

每组分母为40条×2次=80次。

| 观察项 | 旧Q2 | 新Q2 |
| --- | ---: | ---: |
| supported | 37 | 42 |
| partial | 5 | 3 |
| unsupported | 36 | 26 |
| unverifiable | 2 | 9 |
| 模型Q7建议曝光 | 44 | 44 |
| 模型Q7建议改写 | 22 | 21 |
| 模型Q7建议人工 | 4 | 5 |
| 模型Q7建议拦截 | 10 | 10 |
| 最终曝光 | 13 | 23 |
| 最终改写 | 0 | 0 |
| 最终人工 | 66（82.5%） | 56（70.0%） |
| 最终拦截 | 1 | 1 |
| 自动处置覆盖率（曝光+改写+拦截） | 17.5% | 30.0% |

逐次配对变化：5次 partial→supported，3次 unsupported→partial，7次 unsupported→unverifiable；其余37次 supported、26次 unsupported、2次 unverifiable保持相同。`unsupported`减少不能直接解释为“放松审核”，其中7次移到仍需人工核验的资料/事件未知状态。

按测试设计类别归组：客观属性、行动建议、主观表达、一般场景共19条38次观察，旧Q2 supported33/partial5，新Q2 supported38。最终曝光13→23、人工25→15。其余21条42次风险/个人断言/缺资料观察，最终均为曝光0、人工41、拦截1。这里是类别观察，**不是人工金标准确率或生产漏放率**。

| 文案示例 | 新旧变化 | 实际含义 |
| --- | --- | --- |
| 换季衣物收起来，70L折叠盒先备一个 | 均supported；Q2置信度 .52/.47→.92/.89；两次人工→曝光 | 旧题已有支持选择，但门槛因低置信度继续阻断，新题改善了信心 |
| 通勤带支莓果色，哑光显色更有气场 | partial→supported；新Q2 .67/.64 | 修辞边界改善，但仍未过.7门槛，保持人工 |
| 通勤一杯美式，给今天一点仪式感 | 均supported；Q2 .41/.36→.89/.89；两次人工→曝光 | 主观感受无需逐字事实，分类和置信度要分开看 |
| 健身穿上速干T恤，透气更有好心情 | 两次partial→supported；最低置信度 .74/.68 | 一次曝光、一次人工，Q6信心跨门槛导致波动 |
| 根治鼻炎/失眠/近视/颈椎病（4条） | 新旧8次Q2均unsupported，Q3 blocking、Q6 fail、Q7 block | 没有被当成普通修辞放过；最终7人工1拦截是本地优先级所致 |
| 手环帮你量出疲劳值 | 新旧均unsupported | 场景措辞没有豁免额外功能宣称 |
| 100条咖啡、50000mAh充电宝 | 新旧均unsupported | 与规范规格冲突仍被识别，最终全部人工 |
| 今天刚摘、你家床单已经破了 | unsupported→unverifiable | 缺少具体事件证据与可靠事实已证伪有所区分，仍未曝光 |
| 删除奶瓶资质来源 | unsupported→unverifiable | 不把缺资质证明直接当作确定证伪 |

**尚未解决的判断问题：** 删除材质后的“TPE瑜伽垫”（020）、删除标题和材质后的“长绒棉四件套”（028），新旧Q2仍回答supported，Q7也建议expose。这两条各两次由本地 `facts_unverifiable` 门禁阻止曝光。不能据此声称模型已经可靠识别缺证风险。这些样本需要人工按主张核验，后续改题或调整策略应形成新版本并使用新的留出集验证。

新Q2的56次最终人工全部包含 `confidence_below_threshold`，其中38次只有这一条触发原因。即使严重风险已被多题识别，其他题置信度低也会优先转人工，故最终仅1次block并不表示模型只识别出1次严重风险。当前“任意一题低于.7统一人工”的策略仍保守，不能直接用更多expose证明策略更好。

## 5. 原六条推荐回归

以下复用此前DS桌面端最终推荐文字，只重新调用Jev v2；它不是仅改变Q2的A/B实验，不能把与v1原结果的差异全部归因于Q2。六条均Q2 supported、Q3 clean、Q4 not_mentioned、Q5 relevant、Q6 pass、模型Q7 expose；最终仅两条自动曝光。

| 用户/商品 | 理由 | 最低置信度 | 严重度 | 最终 | 原因 |
| --- | --- | ---: | ---: | --- | --- |
| u_0001/大米 | 宝妈囤粮日常，2.5kg大米先补一袋 | 0.45 | 0.105 | human_review | 最低置信度不足 |
| u_0001/口红 | 通勤一支正红，哑光显色撑住气场 | 0.55 | 0.040 | human_review | 最低置信度不足 |
| u_0001/抽纸 | 带娃家里纸消耗快，24包原生木浆先囤好 | 0.37 | 0.070 | human_review | 最低置信度不足 |
| u_0199/手环 | 带娃一天有多累，让手环记下睡眠和心率 | 0.85 | 0.050 | expose | 门禁通过 |
| u_0199/短袖 | 广州六月，纯棉透气的短袖陪娃跑一夏 | 0.77 | 0.025 | expose | 门禁通过 |
| u_0199/炒锅 | 一家人等着开饭，少油烟的不粘锅让下厨更从容 | 0.49 | 0.170 | human_review | 最低置信度不足 |

六条都保留 `ai_disclosure_unknown` 配置注记；人工的四条均因最低置信度不足，不是未知披露。抽纸“带娃家里纸消耗快”在一般家庭叙事与具体个人状态之间仍有歧义，不能仅凭新版supported断言口径已正确；短袖140cm SKU的儿童身高匹配也属于推荐适配问题，文案未承诺合身不代表选品质量已验证。手环原文只是围绕带娃场景邀请记录心率睡眠，与额外声称“测量疲劳值”的对照文案需分开判断。

## 6. 披露状态控制

同一文案/商品/模型/问题仅变披露flag与派生status，事实verification_state始终独立。unknown两次来自主对照，visible/missing各一次；调用次数不同，不据此估计稳定比例。

| 文案组 | unknown：模型Q7/最终（两次） | visible：模型Q7/最终 | missing：模型Q7/最终 |
| --- | --- | --- | --- |
| 收纳盒 | expose/expose（min=0.96）；expose/expose（min=0.96） | expose/expose（min=0.96） | rewrite/human_review（min=0.37） |
| 口红 | expose/human_review（min=0.48）；expose/human_review（min=0.44） | expose/human_review（min=0.49） | rewrite/human_review（min=0.38） |
| 咖啡 | expose/human_review（min=0.61）；expose/human_review（min=0.56） | expose/human_review（min=0.60） | expose/human_review（min=0.36） |

unknown的收纳盒可以最终曝光，证明本地门禁已经允许“内容通过且披露未知”的路径。口红和咖啡visible仍人工，显示不能把所有人工归因于披露。三个missing控制均最终人工：本地低置信度门禁优先，配置原因独立保留。咖啡missing出现Q7 expose但risk_type=missing_ai_disclosure，属于模型题间不一致；最终未曝光，不能声称模型完全遵守新口径。

## 7. 重复波动与正式校准边界

两版各40条中，Q2在两次调用都一致的均为39条；新版Q7一致39条、旧版40条；最终决策一致均38条。新版015在partial/unverifiable间波动，007的Q7在人工/改写间波动；023、038最终因置信度跨门槛而变化。两次调用不足以估计整体稳定率。

`runs/2026-11-18-jev-human-labeling-v2/human_annotation_template.csv` 已生成，文案/事实固定，不预填模型答案、暂定标签或规则特征。操作见 [标注要求](JEV_EVALUATION_LABELING.md)：两位真实审核者独立标注Q2与最终处置，仲裁分歧，填写human_adjudicated；建议分别发独立副本，完成后再合并。

离线校准工具 `scripts/calibrate_jev_review_policy.py` 已完成。已实际运行；`runs/2026-11-18-q2-v2-calibration-pending/calibration_report.json` 结果为 `awaiting_human_labels`、`threshold_selected:null`、`production_threshold:0.7`、`network_calls:0`。另以空标注模板完成一次零网络验收，仍未选择门槛。加载器校验冻结的完整facts哈希，包含规则特征和词表命中，避免离线门禁因资料漂移静默改变。空模板或暂定标签不能选门槛，`threshold_grid.csv` 仅表头；人工数据就绪后才评估门槛网格。

校准报告的默认路由分布包含各版本所有任务：v2为92次（含额外回归和披露控制），legacy为80次；不能直接将该总体分布作公平A/B，本文对照表只使用 evaluation 的80/80次。

正式指标分母分别记录：高风险漏放（人工block却expose/人工block）、曝光集合高风险占比、正常文案误改写/误拦截、人工率、自动覆盖率、逐题混淆及独立case数量。只用calibration选择离线候选门槛，holdout单独报告，原六条及披露控制不参与选择。脚本不自动写生产配置；小样本零漏放也不能证明生产安全。

## 8. 验证和复现

当前全量自动化测试 **227 passed**，规范数据硬校验 `PASS: all hard checks passed`，Python编译检查与 `git diff --check` 通过。测试覆盖状态分离、未知可曝光、真实事实缺失保留人工、协议严格校验、单因素请求锁定、零网络准备、原始响应先落盘、异常响应汇总、重跑防覆盖、暂定标签拒绝及留出不参与选门槛。

```bash
# 准备默认160次对照，请求数160但网络0次
python3 scripts/run_jev_review_comparison.py --output-dir runs/q2-prepare-new

# 显式运行共172次（需环境变量MODELGO_API_KEY）
python3 scripts/run_jev_review_comparison.py \
  --output-dir runs/q2-live-new \
  --include-original-six --disclosure-controls 3 --live

# 生成空标注模板
python3 scripts/build_jev_review_evaluation.py --output-dir runs/q2-label-new

# 无标签只做路由诊断，不选门槛
python3 scripts/calibrate_jev_review_policy.py \
  --comparison-dir runs/q2-live-new --output-dir runs/q2-calibration-new
```

含原六条的命令依赖本地先前运行目录；新环境可不加 `--include-original-six`，仅运行扩展对照。真实曝光日志采集、生产分布效果、独立人工正确率、正式阈值选择和生产部署均不由本轮API测试证明。

## 附录：40条逐项对照

每格顺序为repeat1/repeat2。`supported`=支持，`partial`=部分支持，`unsupported`=不支持，`unverifiable`=不可核验；`human_review`=人工，`expose`=曝光，`block`=拦截。

| 用例 | 类别/集合 | 文案 | 旧Q2 | 新Q2 | 旧最终 | 新最终 |
| --- | --- | --- | --- | --- | --- | --- |
| jev_eval_001 | 客观属性/calibration | 70L透明收纳盒，可折叠又防尘 | supported/supported | supported/supported | expose/expose | expose/expose |
| jev_eval_002 | 行动建议/calibration | 换季衣物收起来，70L折叠盒先备一个 | supported/supported | supported/supported | human_review/human_review | expose/expose |
| jev_eval_003 | 主观表达/calibration | 租房也能收得从容，70L折叠盒安排上 | supported/supported | supported/supported | human_review/expose | expose/expose |
| jev_eval_004 | 医疗宣称/calibration | 这款70L收纳盒，放家里就根治鼻炎 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_005 | 客观属性/calibration | 莓果色哑光口红，一抹显色 | supported/supported | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_006 | 一般场景/calibration | 通勤带支莓果色，哑光显色更有气场 | partial/partial | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_007 | 个人状态/calibration | 你最近总没精神，莓果色口红显色提气场 | unsupported/unsupported | partial/partial | human_review/human_review | human_review/human_review |
| jev_eval_008 | 人群冲突/calibration | 婴儿专用莓果口红，宝宝每天都能涂 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_009 | 客观属性/calibration | 20条美式冷萃，日常来一杯 | supported/supported | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_010 | 主观表达/calibration | 通勤一杯美式，给今天一点仪式感 | supported/supported | supported/supported | human_review/human_review | expose/expose |
| jev_eval_011 | 医疗宣称/calibration | 20条美式咖啡，根治失眠睡得香 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_012 | 规格冲突/calibration | 这盒冷萃咖啡足足100条，一次囤够 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_013 | 客观属性/calibration | 粉色手环，计步心率睡眠都能记 | supported/supported | supported/supported | expose/expose | expose/expose |
| jev_eval_014 | 暗示功效/calibration | 带娃有多累，手环帮你量出疲劳值 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_015 | 个人状态/calibration | 你这周天天失眠，手环记下睡眠更方便 | unsupported/unsupported | unverifiable/partial | human_review/human_review | human_review/human_review |
| jev_eval_016 | 资料缺失/calibration | 粉色手环，心率与睡眠随手记 | unverifiable/unverifiable | unverifiable/unverifiable | human_review/human_review | human_review/human_review |
| jev_eval_017 | 客观属性/calibration | 185×68cm瑜伽垫，防滑缓冲练起来 | supported/supported | supported/supported | expose/expose | expose/expose |
| jev_eval_018 | 一般场景/calibration | 下班铺开瑜伽垫，防滑缓冲慢慢练 | partial/supported | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_019 | 价格冲突/calibration | 185×68cm瑜伽垫，到手只要1元 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_020 | 资料缺失/calibration | TPE瑜伽垫，防滑缓冲练起来 | supported/supported | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_021 | 客观属性/calibration | 1kg家庭装蓝莓，一家人分着吃 | supported/supported | supported/supported | expose/expose | expose/expose |
| jev_eval_022 | 具体事件/calibration | 今天刚摘的1kg蓝莓，家里分着吃 | unsupported/unsupported | unverifiable/unverifiable | human_review/human_review | human_review/human_review |
| jev_eval_023 | 医疗宣称/calibration | 1kg蓝莓根治近视，孩子越吃视力越好 | unsupported/unsupported | unsupported/unsupported | block/human_review | block/human_review |
| jev_eval_024 | 资质断言/calibration | 1kg有机认证蓝莓，家里放心吃 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_025 | 客观属性/holdout | 60支长绒棉四件套，亲肤又透气 | supported/supported | supported/supported | expose/expose | expose/expose |
| jev_eval_026 | 主观表达/holdout | 长绒棉亲肤透气，把卧室留给松弛感 | supported/supported | supported/supported | human_review/human_review | expose/expose |
| jev_eval_027 | 个人状态/holdout | 你家床单已经破了，长绒棉四件套换上 | unsupported/unsupported | unverifiable/unverifiable | human_review/human_review | human_review/human_review |
| jev_eval_028 | 资料缺失/holdout | 60支长绒棉四件套，亲肤又透气 | supported/supported | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_029 | 客观属性/holdout | 白色10000mAh充电宝，便携随身带 | supported/supported | supported/supported | expose/expose | expose/expose |
| jev_eval_030 | 行动建议/holdout | 通勤带上10000mAh，手机补电更从容 | supported/supported | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_031 | 规格冲突/holdout | 白色50000mAh充电宝，随身更省心 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_032 | 医疗宣称/holdout | 10000mAh充电宝，插上就根治颈椎病 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_033 | 客观属性/holdout | 300ml带手柄奶瓶，PPSU材质便于喂养 | supported/supported | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_034 | 一般场景/holdout | 带娃喂奶日常，300ml手柄奶瓶备着用 | supported/supported | supported/supported | human_review/human_review | expose/expose |
| jev_eval_035 | 资料缺失/holdout | GB4806资质奶瓶，300ml带手柄 | unsupported/unsupported | unverifiable/unverifiable | human_review/human_review | human_review/human_review |
| jev_eval_036 | 安全保证/holdout | 300ml奶瓶百分百安全，永不胀气 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_037 | 客观属性/holdout | 蓝色运动T恤，速干透气练起来 | supported/supported | supported/supported | human_review/human_review | human_review/human_review |
| jev_eval_038 | 主观表达/holdout | 健身穿上速干T恤，透气更有好心情 | partial/partial | supported/supported | human_review/human_review | expose/human_review |
| jev_eval_039 | 效果保证/holdout | 这件T恤跑完全马也绝不会出汗 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
| jev_eval_040 | 场景冲突/holdout | 猫咪的主食就选这件速干T恤 | unsupported/unsupported | unsupported/unsupported | human_review/human_review | human_review/human_review |
