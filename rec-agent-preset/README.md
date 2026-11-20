# Rec-Agent Preset

面向电商推荐的 DeepSeek Harness Agent 预设。输入用户 ID，查询画像、行为、推荐反馈和商品数据，输出 1–3 个商品及曝光理由，供独立 Jev 工作流审核。

## 安装

在支持本地插件 bundle 的 DeepSeek Harness 中，使用插件管理器的 `install_bundle` 安装本目录。

| 项目 | 值 |
| --- | --- |
| Bundle 包名 | `@local/dsh-rec-agent-preset` |
| Preset ID | `rec-agent` |
| 显示名称 | `Rec-Agent` |
| Loader ID | `preset-rec-agent` |

将仓库根目录设为工作区，并按[工作区配置说明](../harness-main-workspace.md)连接 MCP 数据服务。安装后在 Agent 选择器中选择 **Rec-Agent**，新建会话即可使用。更新预设后重新安装 bundle，并新建会话以加载配置。

## 输入

```json
{
  "user_id": "u_0007"
}
```

也支持传入 `user_context` 对象，用于自定义画像与场景。当前规范数据审核工作流按 `u_####` 用户 ID 重建事实；如需接入自定义画像，应同时扩展审核数据契约。

## 输出

最终回答为两空格缩进的严格 JSON 对象：

| 字段 | 内容 |
| --- | --- |
| `user_id` | 用户 ID |
| `user_profile` | 用户画像摘要 |
| `recommendations` | 按优先级排序的推荐列表 |
| `recommendations[].item_id` | 规范商品 ID |
| `recommendations[].title` | 商品完整标题 |
| `recommendations[].exposure_reason` | 商品卡展示的曝光理由 |
| `recommendations[].generated_reason` | 与曝光理由相同的兼容字段 |
| `recommendations[].evidence_fields` | 支撑文案的事实字段路径 |
| `recommendations[].context_summary` | 推荐依据摘要 |
| `agent_version` | `rec-agent-v2` |

用户不存在或没有可推荐商品时，`recommendations` 为空数组，并通过顶层 `context_summary` 说明原因。预设包含输出校验与修复机制；无效结果会报错。

## 数据访问

优先使用只读 MCP 工具查询画像、行为、推荐历史、会话场景、商品与促销。未连接 MCP 时，读取工作区 `data/raw/`；原始文件不可用时可使用 `data/mock.db`。

历史反馈用于软排序、去重与探索。无历史反馈的用户依靠画像、行为、场景和商品信息完成首轮推荐。反馈不作为商品事实传给 Jev。

## 审核交接

预设负责推荐生成，审核由 Harness 外的独立工作流完成。保存最终 JSON 后，按[独立工作流说明](../docs/STANDALONE_WORKFLOW.md)运行 Jev，或使用[可视化工作台](../docs/WEB_UI.md)查看完整链路。

### 预设文件

| 文件 | 作用 |
| --- | --- |
| `cordis.patch.yml` | 角色、数据访问及输出配置 |
| `strict-output.js` | 严格 JSON 输出校验 |

---

[返回项目首页](../README.md) · [数据说明](../data/README.md)
