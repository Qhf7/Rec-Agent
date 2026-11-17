# Rec-Agent 主工作区配置

当前统一工作区：

`/Users/qiaohongfei/Desktop/实习/Jev曝光审核`

## Harness preset

- Bundle：`rec-agent-preset/`
- MCP bundle：`rec-agent-mcp/`
- Preset ID：`rec-agent`
- 显示名：`Rec-Agent`
- 输出字段：`exposure_reason`（用户可见）、`generated_reason`（兼容别名）、`evidence_fields`、`context_summary`

## MCP 启动

在主工作区运行：

```bash
python3 mcp_server.py
```

默认使用 stdio transport。工具包括：

- `get_user_profile`
- `get_user_behavior`
- `get_user_recommendation_history`
- `get_session_context`
- `search_items`
- `get_item`
- `get_promo`

Harness 中对应的工具名为：`mcp__rec-agent-data__get_user_profile`、
`mcp__rec-agent-data__get_user_behavior`、`mcp__rec-agent-data__get_user_recommendation_history`、
`mcp__rec-agent-data__get_session_context`、
`mcp__rec-agent-data__search_items`、`mcp__rec-agent-data__get_item`、
`mcp__rec-agent-data__get_promo`。

这些工具只读 `data/raw/` 和 `data/recommendation_feedback_history.csv`，不修改数据，也不调用 Jev。推荐历史只提供给 Rec-Agent 做候选排序参考，不会进入 Jev 审核输入。

事件级参考数据位于 `data/recommendation_feedback_history.csv`：每行是一条已通过 Jev 并实际展示的推荐事件，包含 `event_time`、`exposure_reason`、`clicked`、`click_time`、`position`、`traffic_source`、`device_type` 和 `session_id`。它是合成冷启动演示数据，接入真实链路后应由展示服务按同一字段追加真实反馈。

## 测试输入

```json
{"user_id":"u_0007"}
```

用户卡片只展示 `exposure_reason`；`evidence_fields` 和 `context_summary` 留给 Jev 审核与审计。
最终回答使用格式化 JSON，前后不附加英文过程说明；如果界面仍显示旧的压缩 JSON 或 `rec-agent-v1`，请完全重启 Harness 并新建会话。

每次修改 `rec-agent-preset/cordis.patch.yml` 后，需要完全退出并重新打开 DeepSeek Harness，再新建会话验证。旧会话会保留历史响应；如果输出中的 `agent_version` 仍是 `rec-agent-v1`，说明看到的是旧结果。本次文案策略版本为 `rec-agent-v2`。

## 独立结果查看器

Harness 的消息区域可能压缩 JSON 空白。可打开主工作区中的 [rec-agent-viewer.html](</Users/qiaohongfei/Desktop/实习/Jev曝光审核/rec-agent-viewer.html>)，把 Harness 整段输出粘贴进去，点击“格式化结果”。查看器会保留原始输入，并在右侧独立生成 2 个空格缩进、逐项换行的结果；“复制格式化结果”可以直接复制可读版本，同时下方展示用户画像和推荐卡片。

命令行也可以格式化结果：

```bash
pbpaste | python3 scripts/format_rec_agent_output.py
```

如果只需要缩进后的 JSON：

```bash
pbpaste | python3 scripts/format_rec_agent_output.py --json-only
```
