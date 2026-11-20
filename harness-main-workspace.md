# DeepSeek Harness 工作区配置

桌面 Harness 使用 Rec-Agent 预设生成推荐 JSON；MCP 提供只读数据查询。Jev 审核由独立工作流执行。

## 连接工作区

1. 将克隆的仓库根目录设为 Harness 工作区。
2. 使用插件管理器安装 [`rec-agent-preset/`](rec-agent-preset/) bundle。
3. 配置 MCP 数据服务：将 [`rec-agent-mcp/cordis.patch.yml`](rec-agent-mcp/cordis.patch.yml) 中的 `args` 改为本机 `mcp_server.py` 的绝对路径，`cwd` 改为仓库根目录，再安装该 bundle。
4. 在 Agent 选择器中选择 **Rec-Agent**，新建会话。

MCP 使用 stdio 传输。手动启动命令为：

```bash
python3 mcp_server.py
```

运行前安装依赖：

```bash
python3 -m pip install -r requirements-mcp.txt
```

## 数据工具

| 工具 | 数据 |
| --- | --- |
| `get_user_profile` | 用户画像 |
| `get_user_behavior` | 行为与兴趣 |
| `get_user_recommendation_history` | 历史推荐曝光与点击反馈 |
| `get_session_context` | 场景与时间 |
| `search_items` | 商品检索 |
| `get_item` | 商品详情 |
| `get_promo` | 促销规则 |

Harness 中的工具名可能带 `mcp__rec-agent-data__` 前缀。规范数据位于 `data/raw/`，商品 ID 为 `i_####`；反馈位于 `data/recommendation_feedback_history.csv`。详见[数据说明](data/README.md)。

## 生成推荐

输入：

```json
{
  "user_id": "u_0007"
}
```

最终回答包含用户画像、商品与曝光理由，格式为严格 JSON。输出字段见[预设文档](rec-agent-preset/README.md)。工具查询轨迹可在 Harness 轨迹面板查看。

## 查看与导出

复制最终回答并保存为 `harness-result.json`，交给[独立工作流](docs/STANDALONE_WORKFLOW.md)审核。也可打开 [`rec-agent-viewer.html`](rec-agent-viewer.html)，粘贴内容查看商品卡片和格式化 JSON。

已有文本文件可通过命令行提取并格式化 JSON：

```bash
python3 scripts/strict_json_output.py < harness-output.txt > harness-result.json
```

macOS 可从剪贴板读取：

```bash
pbpaste | python3 scripts/strict_json_output.py > harness-result.json
```

应复制完整最终回答；工具结果预览可能省略字段，不适合作为导出文件。

---

[返回项目首页](README.md) · [可视化工作台](docs/WEB_UI.md) · [独立工作流](docs/STANDALONE_WORKFLOW.md)
