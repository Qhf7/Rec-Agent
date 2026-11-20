# Rec-Agent 可视化工作台

输入用户 ID，工作台依次读取画像与推荐反馈、生成商品及曝光理由、调用独立 Jev 审核，最后将商品、文案和审核结果放在同一张卡片中展示。

## 在线体验

访问 **[qhf7.github.io/Rec-Agent](https://qhf7.github.io/Rec-Agent/)**，无需安装或登录，即可查看完整交互界面。公开站点使用保存的真实推荐与审核结果，支持三个示例用户、审核详情、评分图表、浏览器运行记录和 JSON 导出；不发起新的模型调用。没有公开实测记录的已知用户会提示选择示例，不会假装实时生成。

GitHub Pages 只托管静态资源，实时生成需要独立后端。本地工作台保留实时模式；公开站点不包含模型密钥，运行历史仅保存在当前浏览器。

`.github/workflows/pages.yml` 在相关文件推送到 `main` 后自动构建并部署，亦支持手动运行。`scripts/build_pages.py` 仅复制明确列出的网页资源、模拟用户 ID 索引和公开实测数据，不发布本机 `runs/`、环境配置或后端源码。资源使用相对路径，兼容仓库子路径 `/Rec-Agent/`。

本地验证公开版本：

```bash
node --test tests/static-api.test.js
python3 scripts/build_pages.py --output runs/pages-preview/Rec-Agent
python3 -m http.server 8790 --bind 127.0.0.1 --directory runs/pages-preview
```

打开 `http://127.0.0.1:8790/Rec-Agent/`。构建目录需新建或为空；再次验证时使用新输出目录。

公开版本已通过 8 项静态适配测试，并用真实浏览器检查了仓库子路径、默认演示、冷启动用户、已知用户缺少样例提示、未知用户空结果、详情、JSON 下载、刷新恢复和 390px 手机布局；未向 `/api/` 发起请求。Python 后端回归 520 项通过。

## 启动

在项目根目录运行：

```bash
python3 -m pip install -r requirements-mcp.txt
python3 ui_server.py
```

浏览器打开 [http://127.0.0.1:8787](http://127.0.0.1:8787)。服务默认仅监听本机，静态页面和 API 使用同一地址。

## 两种运行方式

| 模式 | 推荐与审核结果来源 | 是否产生新的模型调用 |
| --- | --- | --- |
| 已录制样例 | 2026-11-20 桌面 Harness 推荐，以及当时真实调用 Jev 得到的结果 | 否 |
| 实时工作流 | 网页服务中的独立推荐 Agent 生成候选，然后调用 Jev | 是 |

样例可使用 `u_0001`、`u_0199`、`u_0007`。其中 `u_0199` 没有历史推荐曝光点击，工作台仍能展示冷启动结果；`u_9999` 是不存在的用户，返回空结果，不调用 Jev。样例中的吸引力与处置来自保存的真实响应，不是前端随机数或占位结论。

实时模式需要在启动服务的进程环境中配置模型凭据。凭据保留在服务器端，浏览器只收到配置是否可用，不收到密钥。不要将密钥粘贴到用户 ID、导入结果或版本库中。服务不自动读取 `.env`，修改环境后需要重新启动进程。

| 环境变量 | 用途与默认值 |
| --- | --- |
| `MODELGO_API_KEY` | Jev 审核必需；没有独立 DeepSeek 密钥时，也用于 ModelGo 推荐生成 |
| `DEEPSEEK_API_KEY` | 可选；设置后，推荐阶段调用 DeepSeek 接口 |
| `DEEPSEEK_BASE_URL` | DeepSeek 基础地址，默认 `https://api.deepseek.com/v1`，服务追加 `/chat/completions` |
| `DEEPSEEK_MODEL` | 推荐模型；直连默认 `deepseek-chat`，ModelGo 默认 `deepseek-v4-flash` |

例如，仅使用现有 ModelGo 额度时，在终端以隐藏输入配置凭据，然后启动服务：

```bash
read -s MODELGO_API_KEY
export MODELGO_API_KEY
python3 ui_server.py
```

上述 `read -s` 适用于 macOS 默认 zsh；输入已有密钥后按回车，终端不回显密钥。使用 DeepSeek 独立额度时，同样配置 `DEEPSEEK_API_KEY`，并保留 Jev 使用的 `MODELGO_API_KEY`。API 地址、模型及连接状态可以在页面中核对。配置不完整或调用失败会明确报错，不自动切换为样例结果。

实时推荐使用项目中的独立 Web Harness：先根据画像、行为与反馈检索最多 36 个候选，再由大模型选择 3 个商品并生成理由，复用规范商品事实、文案规则与输出约束。它不遥控或复用 DeepSeek Harness 桌面会话。推荐结束后，独立 Jev 阶段才开始；Jev 不作为推荐 Agent 内部工具。

## 页面结果

工作台展示用户与历史反馈摘要、每一阶段的运行状态、推荐商品及短曝光理由，以及 Jev 风险分型、吸引力分、合规状态与最终处置。结果可以导出为严格 JSON，便于后续回放和排查。

运行记录保存在本机 `runs/web-ui/`，重启服务后恢复最近记录；中断任务标为异常，不自动续发付费请求。商品卡的插画仅用于示意，价格与商品属性来自规范模拟数据。

曝光理由不超过 20 个 Unicode 字符，标点计入长度，不包含数量和规格参数；商品完整标题仍保留原始规格。用户画像、行为和历史点击用于上游选品；Jev 只收到独立工作流白名单内的商品、场景、促销、披露与核查信息，历史 CTR、购物车、订单和搜索不传给 Jev。

Jev 只回答两道题：

| 字段 | 回答范围 |
| --- | --- |
| `risk_type` | `compliant` / `absolute_claim` / `efficacy_or_medical_claim` / `price_misleading` / `missing_ai_disclosure` / `off_topic` |
| `attractiveness_score` | 1–100 分，由接口十级评分及其概率换算 |

风险为 `compliant` 时合规为 Y；仅合规 Y 且吸引力严格大于 50 时处置为 `expose`，其他为 `rewrite`。`rewrite` 是需要修改文案的结论，当前页面不会自动重写，也不会创建人工复核任务。页面上的“曝光”表示允许曝光的审核结论，不会向真实用户投放商品。

当前六类风险不包含独立的通用事实核验题，`compliant` 不意味着全部商品事实都经过验证；吸引力分也不代表真实点击率。

## 样例数据与追溯

自包含样例位于 [`web/data/sample-runs.json`](../web/data/sample-runs.json)，可在新克隆的仓库中直接运行。三组结果对应完整测试的 `H1-r1`、`H2-r1`、`H3-r1`，包含 9 条推荐、原始 Jev 审核字段、规范商品、画像和真实模拟反馈摘要。样例不依赖被 Git 忽略的本机 `runs/` 目录。

这里的“真实响应”指真实模型接口调用的结果；用户、商品和反馈数据仍属于项目的模拟数据。推荐理由来自桌面最终答复的无改写转录，画像与商品由规范数据核对，来源保存在每个样例的 `provenance` 中。完整分析见[多轮测试报告](TEST_REPORT_JEV_MULTIROUND_2026-11-20.md)。

更多协议细节见[当前问题、输入与处置说明](JEV_QUESTIONS_INPUT_DECISION_GUIDE.md)。

界面截图、浏览器检查及两轮实时模型结果见[工作台测试记录](TEST_REPORT_WEB_UI_2026-11-20.md)。
