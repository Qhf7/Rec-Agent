# 曝光广告文案生成

已使用桌面版保存的 `deepseek123` 提供商与 `deepseek-v4.1-flash-1017` 模型完成两个新会话测试，见[桌面真实测试记录](TEST_REPORT_HARNESS_DEEPSEEK123_2026-11-18.md)。桌面使用已保存凭据；下文 Python 批量入口有自己的接口配置，不会自动读取桌面提供商密钥。

Rec-Agent 的曝光理由由大模型依据商品关键信息创作，输出到 `exposure_reason`；`generated_reason` 保存完全相同的兼容值。用户画像和行为负责帮助选品、选择相关场景，商品事实负责支撑文案中的客观卖点。

## 创作过程

1. 查询商品详情，提炼 1–2 个有用卖点，记录原始字段路径。
2. 根据兴趣与场景选择日常用途，例如擦手擦嘴、开火做饭、散步记录步数。
3. 在内部拟写 2–3 个不同开头，按自然广告语气、事实支撑与句式多样性择优。仅返回选中的文案。
4. 核对客观描述、使用动作、基准日期、20 字符上限及证据字段，再输出严格 JSON。

允许自然的邀请、主观感受、感叹号和语气词，最多一个 emoji。曝光理由保持单行，建议 8–18 个字符，总长度最多 20 个 Unicode 字符，标点、字母和 emoji 均计入。由模型直接创作短文案，不截断句子。文案聚焦商品功能、材质或有依据的使用特点，不出现包装数量、尺寸、容量、型号、数值或技术参数，包括中文数量形式。自然措辞如「一抹」「三餐」可以保留。完整商品标题保留用于识别，数量约束只针对曝光文案。

## 事实与语气的边界

| 信息 | 如何使用 |
| --- | --- |
| 功能、材质、标题中的真实特性 | 选择其中 1–2 项融入广告表达；注明直接支撑文案的 `items.*` 路径 |
| 商品适用人群 | 选择一般用途，不代表某个用户正处于该状态 |
| 画像、兴趣、购物车、搜索、点击历史 | 用于上游选品与场景选择；行为记录不进入可见文案或 Jev 输入 |
| 用户家庭与生活状态 | 不从标签推导纸张消耗、接娃安排、家庭人数或具体生活事件 |
| 语气参考中的卖点 | 只有当前商品字段支持时才能使用；参考文案本身不是事实来源 |
| 规格与参数 | 保留在商品事实和完整标题中供识别；不进入曝光文案 |
| 日期与季节 | 使用数据快照基准，不自行添加天气或与本次日期冲突的季节场景 |

例如，当前 `i_0006` 支持原生木浆、清洁与吸水，可创作「原生木浆抽纸，清洁随手抽」；这些字段没有证明柔软、不掉屑、湿水不破或婴儿适用。可以创作有画面感的擦拭场景，具体卖点仍需回指事实。

`evidence_fields` 保持 2–6 项，至少一项商品字段；仅记录直接支撑最终文案且实际传入的字段。生成新文案时主证据与审计摘要一起更新，模型失败会记录错误。

## 两个生成入口

- DeepSeek Harness：[`cordis.patch.yml`](../rec-agent-preset/cordis.patch.yml) 定义查询、选品与创作规则。修改后重新加载预设并新建 Session；已启动 Session 保留旧指令。可完全退出并重新打开 Harness 后选择 Rec-Agent 测试。
- Python 批量生成：[`recommendation_copy.py`](../recommendation_copy.py) 提供共享事实 brief 与创作规则；[`modelgo_agent.py`](../modelgo_agent.py) 将其发送给 DeepSeek；[`generate_agent_candidates.py`](../generate_agent_candidates.py) 合并规范候选、更新证据。

Harness 中输入：

```json
{"user_id":"u_0001"}
```

重点检查文案是否只保留突出卖点、句式自然，以及是否把画像变成具体家庭状态断言。输出 Schema、用户 ID 和商品 ID 契约保持一致。

批量接口默认只预览请求，可用已有规范候选执行：

```bash
python3 generate_agent_candidates.py \
  --source reason_candidates.jsonl \
  --limit 10 \
  --request-output runs/copy-preview/requests.jsonl \
  --report runs/copy-preview/report.json
```

设置 `MODELGO_API_KEY` 后显式添加 `--send` 才调用模型；使用新的输出路径保存结果：

```bash
python3 generate_agent_candidates.py \
  --source reason_candidates.jsonl \
  --limit 10 --send \
  --natural-output runs/copy-live/natural.jsonl \
  --full-output runs/copy-live/full.jsonl \
  --report runs/copy-live/report.json
```

自然候选中同一用户可以有多个商品，同一用户与商品组合应只保留一条输入。`natural.jsonl` 保存本轮模型成功生成的候选；`full.jsonl` 还可能包含来源数据中明确标注的压力测试记录。默认预览不会覆盖这两个候选文件。

## 桌面端严格 JSON 输出

预设内的 [`strict-output.js`](../rec-agent-preset/strict-output.js) 接入 Harness 官方 `llm/stream` 扩展点，按会话隔离：

1. 缓冲每一步的模型输出；工具调用原样保留，工具前后的自然语言状态文字不作为回答发布。
2. 最终结果整段解析为一个严格 JSON 对象，拒绝前后说明、Markdown、多个根值、重复键和非有限数字。
3. 校验字段、类型、兼容别名、证据字段、20 字符上限与参数表达；成功后统一两空格缩进。
4. 校验失败时用同一提供商与模型请求修复，最多两次；仍失败则本轮报错，不发布无效 JSON。修复调用不开放工具，不作 Jev 判决。序列化后的行尾使用 Markdown 硬换行标记，保持 Harness 消息区的逐行显示；额外空格属于 JSON 合法空白。

修改后完全退出并重新打开桌面 Harness，新建会话、选择 Rec-Agent。历史会话保留原预设修订。界面可折叠工具轨迹，复制最终回答得到完整 JSON；已有历史消息仍可使用格式化脚本或查看器。

## 交给独立 Jev 工作流

模型生成完成后，由调用方单独运行：

```bash
python3 scripts/run_recommendation_workflow.py \
  --input runs/copy-live/natural.jsonl \
  --input-format jsonl \
  --output-dir runs/copy-review-prepare
```

默认仅准备事实与请求。使用 `--live` 调用 Jev 后，独立工作流汇总五题答案，并在合规且吸引力严格大于 50 分时输出 `expose`。见 [题目及处置标准](JEV_QUESTIONS.md)。
