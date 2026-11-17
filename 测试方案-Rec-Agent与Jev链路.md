# Rec-Agent 与 Jev 链路测试方案

本文用于验证主工作区中的数据层、MCP 服务、Rec-Agent、事实包和 Jev 审核链路。测试数据均来自虚构 Mock 数据。

## 一、自动化基础回归

```bash
pytest -q
python3 scripts/validate_data.py
```

通过标准：

- pytest 全部通过；
- 数据校验输出 `PASS: all hard checks passed`；
- 用户 200 条、商品 200 条、促销规则 30 条、SQLite 数据行数一致。

## 二、MCP 工具测试

| 编号 | 输入 | 验证点 | 预期结果 |
|---|---|---|---|
| M1 | `get_user_profile("u_0007")` | 用户画像查询 | `found=true`，城市为成都，包含食品生鲜偏好 |
| M2 | `get_user_behavior("u_0007")` | 行为查询 | 购物车包含 `i_0092`，搜索词包含“大米”和“家用” |
| M3 | `get_item("i_0057")` | 商品事实查询 | 返回冷萃咖啡液、20条美式、上班族和库存字段 |
| M4 | `search_items(query="大米")` | 关键词检索 | 返回大米类商品，不能返回不存在的 item_id |
| M5 | `get_promo(item_id="i_0057", as_of="2026-06-15")` | 活动核验 | 返回有效规则 P012，标记 `active=true` |
| M6 | `get_promo(item_id="i_0064", as_of="2026-06-15")` | 门槛活动 | 返回 P018，但不能仅凭商品单价断言“满99赠礼”已满足 |
| M7 | `get_user_profile("u_9999")` | 未知用户 | 返回 `found=false`，不得生成虚构画像 |
| M8 | `get_item("i_9999")` | 未知商品 | 返回 `found=false`，不得生成虚构商品 |

可直接运行：

```bash
pytest tests/test_mcp_server.py -q
```

## 三、Rec-Agent 输出契约测试

### R1：正常用户推荐

输入：

```json
{"user_id":"u_0007"}
```

断言：

- `user_id` 为 `u_0007`；
- `recommendations` 数量为 1–3；
- 每个 `item_id` 都存在于商品表且库存大于 0；
- 存在 `exposure_reason`、`generated_reason`、`evidence_fields`、`context_summary`；
- `exposure_reason == generated_reason`；
- `exposure_reason` 是一句面向用户的中文文案，汉字不超过 24 个；
- 文案不能出现 `users.city`、`items.functions`、`evidence_fields` 等内部字段路径。

### R2：未知用户空结果

输入：

```json
{"user_id":"u_9999"}
```

断言：

- `recommendations == []`；
- 顶层 `context_summary` 说明用户不存在；
- 不返回虚构商品、虚构画像或 Jev 判决字段。

### R3：user_context 覆盖快照

输入：

```json
{
  "user_id":"u_0007",
  "user_context":{
    "user_id":"u_0007",
    "city":"杭州",
    "preferred_categories":["家居日用"],
    "active_hours":"22:00-02:00"
  }
}
```

断言：推荐理由使用杭州和家居偏好，不应把成都作为主要场景；`user_context` 的字段优先于 CSV 快照。

### R4：用户可见文案与内部依据隔离

用购物车、搜索词、标签触发推荐，检查：

- 可以把行为转写为自然场景，例如“通勤大容量，更适合日常出门”；
- 不直接输出“你搜过大米”“购物车里的托特包”“用户标签为租房”；
- `context_summary` 可以保留内部依据，但不能复制到 `exposure_reason`。

### R5：促销门槛

- `i_0057`：P012 为无门槛 9 折，可以在事实成立时写“9折”；
- `i_0064`：P018 为满 99 元赠礼，单价不足门槛时不得写“满99赠礼”；
- 已过期或未开始规则不得出现在 `exposure_reason`。

### R6：职责边界

Rec-Agent 输出中不得出现：

```text
decision
risk_type
judge_score
escalated
model_version
score_name
```

这些字段只属于下游 Jev 审核结果。

## 四、Jev 衔接测试

### J1：事实包字段兼容

输入同时带有：

```json
{
  "exposure_reason":"通勤大容量更好装",
  "generated_reason":"通勤大容量更好装"
}
```

断言：事实包保留两个字段，且二者相同；词表命中和 Jev 文本解析使用 `exposure_reason`。

### J2：规则路由

| 场景 | 预期处置 |
|---|---|
| 事实完整、属性支撑充分 | `expose` |
| 绝对化表达但可以机械改写 | `rewrite` |
| 商品关键字段缺失或工具冲突 | `human_review` |
| 未支持的医疗/功效宣称 | `block` |

### J3：Dry-run 安全

```bash
python3 run_jev_batch.py --dry-run \
  --input fact_bundle.jsonl \
  --output /tmp/jev-result.jsonl
```

断言：不发起网络请求，结果包含请求预览和可追溯的 `reason_id`。

## 五、Harness 手工验收

1. 在主工作区 `Jev曝光审核` 新建会话。
2. 选择 `Rec-Agent`。
3. 输入 `{"user_id":"u_0007"}`。
4. 打开“轨迹”标签。
5. 确认出现以下工具调用：
   - `mcp__rec-agent-data__get_user_profile`
   - `mcp__rec-agent-data__get_user_behavior`
   - `mcp__rec-agent-data__get_user_recommendation_history`
   - `mcp__rec-agent-data__get_session_context`
   - `mcp__rec-agent-data__get_item`
   - `mcp__rec-agent-data__get_promo`
6. 确认最终 JSON 中存在 `exposure_reason`，且它与 `generated_reason` 相同。
7. 用 `u_0001` 验证历史路径：轨迹中 `get_user_recommendation_history` 返回 `history_status=warm`，并包含事件或类目统计。
8. 用 `u_0199` 验证冷启动路径：返回 `history_status=cold_start`，但 Agent 仍应根据画像和场景生成推荐，不应直接返回空结果。

## 六、建议的测试顺序

先运行自动化基础回归和 MCP 测试，再做 R1、R2、R5 三个 Agent 场景，最后验证 J1–J3。这样可以先排除数据和工具问题，再判断推荐策略和曝光审核是否正确。
