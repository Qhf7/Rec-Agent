# Rec-Agent 主工作区统一设计

## 目标

把 DeepSeek Harness 当前使用的 `_副本` 工作区内容统一到主项目目录，使用户、商品、促销与场景数据、Rec-Agent preset 和 Jev 评测代码处于同一工作区；同时把用户可见的一句话推荐文案明确命名为 `exposure_reason`。

## 现状与约束

- 主目录已有 Jev 规则基线、事实包、批处理和评测产物。
- `_副本` 已有与 Harness preset 配套的 `data/raw/`、`data/mock.db` 和 `rec-agent-preset/`。
- 不能覆盖主目录已有的 Jev 结果文件；新增 canonical 数据层放在 `data/`。
- 推荐 Agent 只生成商品和用户可见理由，不输出 Jev 的 `decision`、`risk_type` 或 `judge_score`。
- `generated_reason` 继续保留以兼容现有事实包与 Jev 管线，但必须与 `exposure_reason` 相同。

## 方案

采用“同步数据与 preset + 只读 MCP 服务 + 兼容输出字段”的统一方案：

1. 将 `_副本/data/` 和 `_副本/rec-agent-preset/` 同步到主目录。
2. 在主目录增加 `mcp_server.py`，使用 FastMCP 暴露用户、行为、场景、商品和促销查询工具。
3. 将 preset 的输出 Schema 增加 `exposure_reason`，要求它是一句可直接展示给用户的中文文案；`generated_reason` 作为兼容别名。
4. 将 Harness profile 的 link 指向主目录 preset，并通过新会话验证 `Rec-Agent` 可见。

## 不做的事情

- 不覆盖主目录已有平铺数据和 Jev 评测结果。
- 不把 `context_summary`、`evidence_fields` 展示给终端用户。
- 不在 MCP 工具中修改数据或调用 Jev API。

## 验收标准

- `data/` 校验脚本通过，用户、商品、促销和 SQLite 数据可查询。
- MCP 工具可在本地直接调用，并返回结构化结果。
- `rec-agent-preset` 同时包含 `exposure_reason` 与兼容字段 `generated_reason`。
- Harness profile 指向主目录 preset，选择器显示 `Rec-Agent`。
- 现有 Python 测试全部通过。
