# 可视化工作台

输入用户 ID，即可查看推荐商品、曝光理由、Jev 风险判断、吸引力评分和最终处置。工作台支持审核详情、评分图表、运行记录与 JSON 导出，并适配移动端。

## 在线体验

<a href="https://qhf7.github.io/Rec-Agent/"><img src="assets/demo-button.svg" alt="在线体验" width="148" height="42"></a>

公开站点由 GitHub Pages 托管，使用保存的真实模型响应演示完整流程。输入 `u_0001`、`u_0199` 或 `u_0007` 即可体验，无需安装或配置密钥。用户、商品和反馈均为模拟数据。

## 本地启动

在项目根目录运行：

```bash
python3 -m pip install -r requirements-mcp.txt
python3 ui_server.py
```

打开终端显示的访问地址。服务默认仅监听本机；可通过 `--port` 指定端口。

| 模式 | 结果来源 | 模型调用 |
| --- | --- | --- |
| 已录制样例 | 已保存的推荐与 Jev 响应 | 无新增调用 |
| 实时工作流 | 独立 Web Harness 推荐，再调用 Jev 审核 | 需要服务端凭据 |

实时工作流在服务器端执行。桌面 DeepSeek Harness 预设可单独使用，其 JSON 输出也可交给[独立审核工作流](STANDALONE_WORKFLOW.md)。

## 模型配置

在启动服务的终端中设置环境变量；服务不自动读取 `.env`。修改配置后需重启服务。

| 环境变量 | 用途 | 默认值 |
| --- | --- | --- |
| `MODELGO_API_KEY` | Jev 审核；未配置 DeepSeek 独立密钥时也用于推荐 | 必填（实时模式） |
| `DEEPSEEK_API_KEY` | 使用 DeepSeek 接口生成推荐 | 可选 |
| `DEEPSEEK_BASE_URL` | DeepSeek API 基础地址 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 推荐模型 | 直连为 `deepseek-chat`；ModelGo 为 `deepseek-v4-flash` |

例如，在 macOS 默认 zsh 中隐藏输入已有的 ModelGo 密钥：

```bash
read -s MODELGO_API_KEY
export MODELGO_API_KEY
python3 ui_server.py
```

使用 DeepSeek 独立额度时，再设置 `DEEPSEEK_API_KEY`；Jev 仍使用 `MODELGO_API_KEY`。页面可查看模型与配置状态，密钥只保留在服务端环境中。

### 复用桌面 Harness 提供商

推荐端支持 OpenAI Chat Completions 兼容服务。将 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 和 `DEEPSEEK_API_KEY` 设置为桌面 Harness 中同一提供商的配置。例如：

```bash
export DEEPSEEK_BASE_URL="https://www.suanyouyou.com/v1"
export DEEPSEEK_MODEL="deepseek-v4.1-flash-1017"
```

基础地址使用 `/v1`，后端自动追加 `/chat/completions`。密钥通过环境变量提供。也可复制 [`.env.example`](../.env.example) 为本机 `.env`，填写凭据并取消所需配置前的注释，然后在 macOS / Linux 终端加载并启动：

```bash
set -a
source .env
set +a
python3 ui_server.py
```

`.env` 已加入 Git 忽略规则。更新配置后重启服务；独立 Jev 阶段继续使用 ModelGo SystemOne 接口。

## 结果说明

商品卡同时展示商品属性、曝光理由与审核结果。Jev 回答风险分型和吸引力两题：风险为 `compliant` 且吸引力严格大于 50 时，处置为 `expose`；其他情况为 `rewrite`。详见[审核协议](JEV_QUESTIONS.md)。

`expose` 表示允许曝光的审核结论，`rewrite` 表示文案需要修改。当前工作台提供结果展示与导出，实际投放、自动改写和点击采集由业务系统接入。吸引力评分属于模型判断，不代表真实点击率。

用户画像、行为与历史反馈用于推荐。Jev 仅接收审核所需的商品、场景、促销和披露信息，详见[审核输入说明](JEV_JUDGMENT_PROTOCOL.md)。商品插画用于示意。

本地运行记录保存在 `runs/web-ui/`；公开站点的浏览记录保存在当前浏览器。示例数据位于 [`web/data/sample-runs.json`](../web/data/sample-runs.json)。

## GitHub Pages 部署

仓库通过 [Pages 工作流](../.github/workflows/pages.yml)构建并发布静态页面，可在 GitHub Actions 中手动触发。构建命令为：

```bash
python3 scripts/build_pages.py --output runs/pages-site
```

输出目录需新建或为空。构建只发布网页资源、示例结果和用户 ID 索引；实时模型调用需要独立后端。

---

[返回项目首页](../README.md) · [桌面 Harness 配置](../harness-main-workspace.md) · [独立工作流](STANDALONE_WORKFLOW.md)
