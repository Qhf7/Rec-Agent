# 独立推荐准备与 Jev 审核工作流

Harness 只负责查询数据、选品和生成推荐理由。把最终推荐 JSON 导出后，由独立命令完成候选规范化、Fact Bundle 构建和 Jev 请求准备；显式传入 `--live` 才发起 Jev 审核。该命令也可以直接读取离线候选 JSONL，无需启动 DeepSeek Harness 桌面应用。

## 1. 输入

将 Harness 最终答案保存为 UTF-8 严格 JSON，例如 `harness-result.json`：

```json
{
  "user_id": "u_0001",
  "recommendations": [
    {
      "item_id": "i_0001",
      "exposure_reason": "折叠收纳，35L大容量更省心",
      "generated_reason": "折叠收纳，35L大容量更省心",
      "evidence_fields": [
        "items.spec",
        "items.functions"
      ],
      "context_summary": "使用商品规格与折叠收纳功能"
    }
  ],
  "agent_version": "rec-agent-v2"
}
```

- `user_id` 必须是 `data/raw/users.csv` 中存在的 `u_####`；`item_id` 必须是 `data/raw/items.csv` 中存在的 `i_####`。
- `exposure_reason` 和兼容字段 `generated_reason` 可以只提供其中一个；同时存在时必须完全相同。
- 可以提供 `reason_id`，格式为 `r_` 加字母、数字、下划线或连字符。省略时根据用户、商品与理由生成稳定 ID。同一批次不允许重复 ID。
- `evidence_fields` 必须引用实际发送给 Jev 的事实字段。`context_summary` 保存在候选文件中供本地查阅。
- 输入必须是完整 JSON，不接受过程文字、代码围栏、重复键、`NaN` 或 `Infinity`。若复制的是整段对话，先使用 `scripts/strict_json_output.py` 提取最终 JSON。
- 推荐输入不应包含 `decision`、`risk_type`、`judge_score` 或 `escalated` 等审核结论。

`--input-format auto` 默认自动识别 Harness 导出对象或逐行候选。也可以通过 `--input-format harness`、`--input-format jsonl` 明确指定。

候选 JSONL 使用 `rec-candidate-v2`，必须声明 `schema_version` 与 `data_version: canonical-2026-06-15-v1`。旧版 `item_####` 数据先通过独立迁移脚本校验身份，不能直接当作 `i_####` 使用。

## 2. 默认准备请求

在项目根目录执行：

```bash
python3 scripts/run_recommendation_workflow.py \
  --input harness-result.json \
  --output-dir runs/recommendation-prepare-001
```

该步骤读取本地规范数据，生成请求预览，网络调用次数为 0。默认 `--ai-disclosure unknown` 表示实际展示是否带 AI 披露尚未确认，Fact Bundle 会保留此未知状态。

披露状态由运行命令的人根据实际展示配置填写：

| 参数 | 意义 |
| --- | --- |
| `--ai-disclosure unknown` | 默认值；没有披露证明，进入不可验证状态 |
| `--ai-disclosure visible` | 已确认展示中包含所需 AI 披露 |
| `--ai-disclosure missing` | 已确认展示中缺少所需 AI 披露 |

该参数同时适用于导出 JSON 和离线 JSONL。输入中模型自行声明的披露值不作为实际展示证明。

## 3. 单独运行 Jev

检查准备产物后，使用新的输出目录发起审核：

```bash
export MODELGO_API_KEY="<your-api-key>"
python3 scripts/run_recommendation_workflow.py \
  --input harness-result.json \
  --output-dir runs/recommendation-live-001 \
  --ai-disclosure visible \
  --live
```

`--live` 调用现有 `JevAdapter`，鉴权由环境变量提供。未配置密钥会在发起请求前报错。每条候选单独审核，成功结论与错误分别保存；有失败项时命令退出码为 1。运行成功仅表示产生了审计结论，具体是否曝光仍以结论字段为准。

离线候选重放示例：

```bash
python3 scripts/run_recommendation_workflow.py \
  --input runs/recommendation-prepare-001/candidates.jsonl \
  --input-format jsonl \
  --output-dir runs/recommendation-replay-001
```

## 4. 产物

| 文件 | 内容 |
| --- | --- |
| `candidates.jsonl` | 规范候选、理由、证据路径、说明与数据版本 |
| `fact_bundles.jsonl` | 可追溯商品/场景事实、规则特征、披露状态 |
| `jev_requests.jsonl` | 按理由保存的 Jev 请求预览 |
| `jev_decisions.jsonl` | 仅 `--live` 生成；成功返回的审核结论 |
| `jev_errors.jsonl` | 仅有审核失败时生成；按理由记录错误 |
| `workflow_report.json` | 本次模式、数量、版本、调用次数与产物路径 |

输出目录可已存在，但包含同名工作流产物时会拒绝覆盖，请为每次运行选择新的目录。该工作流不生成曝光、点击或反馈记录。

## 5. 事实与版本边界

规范数据版本的场景日期为 `2026-06-15`。新导入 Harness 推荐时，工作流按此场景查询数据，写入 `snapshot_at: 2026-06-15T12:00:00+08:00`；这一时间与命令执行当天无关。报告中的 `scenario_date` 标识该规范数据版本的默认场景日期。

Harness 导出中的商品属性、用户画像和历史统计都不能直接成为 Jev 事实。新导入推荐时，工作流按 ID 从 `data/raw` 加载商品、场景与促销，并记录真实的 `local_csv_lookup`，不伪造 MCP 调用或耗时。

离线候选 JSONL 先校验所有已提供快照的内容与版本。商品/场景/促销存在漂移会直接报错；经过验证的部分快照继续保持部分状态。回放保留原始 `snapshot_at` 和 `tool_trace`，包括空值或缺失状态，不用新的查询记录替代历史轨迹；例如 `2026-06-12` 的候选仍按原始时间回放，空轨迹继续处于不可验证状态。缺字段不会自动补成已验证。旧版数据应在迁移完成后再重放。

候选文件保留 `evidence_fields` 与 `context_summary`，Jev 请求通过独立字段白名单构建。CTR、曝光点击、历史行为与反馈不能进入审计请求，指向未发送事实的证据路径也会被拒绝。Jev 结论始终单独保存，不写回 Harness 推荐结果。
