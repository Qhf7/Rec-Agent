# Rec-Agent Agent Preset

可复用的电商推荐 Agent 预设：根据 `user_id` 或直接传入的 `user_context`，查询当前工作区的用户、商品、促销与场景数据，输出用户信息、1–3 个商品及其可直接展示给用户的曝光理由。推荐理由强调地域、季节、人群、兴趣和场景，不在用户文案中写优惠或折扣。输出严格 JSON，交给下游独立的 Jev 审核链路。

## 安装信息

| 项 | 值 |
|---|---|
| Bundle 包名 | `@local/dsh-rec-agent-preset` |
| Preset ID | `rec-agent` |
| 选择器显示名 | `Rec-Agent` |
| Loader 行 ID | `preset-rec-agent` |
| 顺序 | `5` |
| 来源 | 当前工作区 `rec-agent-preset/`（profile 以 `link:` 安装） |

安装后 `preset-rec-agent` 在 Host Loader 中为 `active`，会出现在 Web 的 Agent 预设选择器中（新建任务的选择器与 Settings 的预设列表；若页面未刷新，刷新一次即可）。

## 组成

- `persona`：Rec-Agent 的角色、输入契约、数据查询优先级、选品规则、事实边界、职责边界、工作步骤与输出 Schema。
- `time-context`：当前日期与时段，用于活跃时段、季节和促销有效期判断。
- `tool-fs`：只读文件工具（read），关闭 write/edit/apply_patch/readImage。
- `tool-fs-search`：glob/grep，用于定位数据文件。
- `tool-bash`（macOS/Linux）或 `tool-pwsh`（Windows）：只读查询数据（python3/sqlite3/grep/awk），关闭后台任务。
- `compaction`：基础压缩与工具结果裁剪，避免大 CSV 读入撑爆上下文。

## 输入

支持两种方式，二者同时提供时 `user_context` 的字段优先（`user_id` 除外）：

```json
{"user_id": "u_0007"}
```

```json
{
  "user_context": {
    "user_id": "u_0007",
    "city": "杭州",
    "active_hours": "22:00-02:00",
    "recent_cart_item_ids": ["i_0031"],
    "preferred_categories": ["家居日用", "母婴亲子"]
  }
}
```

## 数据与工具优先级

1. 若已配置 MCP 工具，优先使用 `get_user_profile`、`get_user_behavior`、`get_user_recommendation_history`、`get_session_context`、`search_items`、`get_item`、`get_promo`（实际名称可能带 `mcp__<server>__` 前缀）。
2. 否则查询工作区文件：
   - `data/raw/users.csv`
   - `data/raw/items.csv`
   - `data/raw/promo_rules.json`
   - `data/raw/city_climate.json`
   - `data/raw/history_reason_stats.csv`（冷启动时的类目 × 理由钩子弱先验）
   - 字段说明：`data/README.md`
3. 原始文件不可用时才使用 `data/mock.db`。

如果已配置 `get_user_recommendation_history`，在画像和行为查询后调用它读取用户最近 30 天的 Jev 通过后曝光反馈。使用 `recent_clicked_item_ids` 和 `category_stats.smoothed_ctr` 做弱偏好，使用 `recent_ignored_item_ids` 降权、`recent_shown_item_ids` 去重。历史只用于软排序、去重和探索位分配，不写入用户可见理由，也不提供给 Jev。`history_status=cold_start` 是正常的首轮状态，应继续依赖画像、购物车、搜索词、场景和商品事实完成推荐。

## 输出（严格 JSON，无 Markdown）

```json
{
  "user_id": "string",
  "user_profile": {
    "city": "string",
    "city_tier": "string",
    "climate_zone": "string",
    "age": 0,
    "gender": "string",
    "life_stage": "string",
    "preferred_categories": ["string"],
    "tags": ["string"],
    "active_hours": "string",
    "price_sensitivity": "string"
  },
  "recommendations": [
    {
      "item_id": "string",
      "title": "string",
      "exposure_reason": "string",
      "generated_reason": "string",
      "evidence_fields": ["string"],
      "context_summary": "string"
    }
  ],
  "agent_version": "rec-agent-v2"
}
```

- `recommendations` 默认 1–3 条，按推荐优先级排序；`title` 直接取商品 `title`。
- `exposure_reason`：唯一的用户可见文案，一句自然、具体、有吸引力的中文，汉字数不超过 24 个；不能出现内部字段、证据路径或「你搜过/购物车里的」等行为追踪措辞。
- `exposure_reason`：不能只是「人群/用途 + 类目 + 规格」的事实罗列，至少要把一个具体场景或身份钩子，与商品事实和心理收益/行动暗示组合起来；例如「一人食刚刚好，1kg五常大米先尝鲜」比「一人食主食，1kg尝鲜装」更符合首页卡片语气。
- `exposure_reason` 不写价格、优惠、折扣、满减、赠品或门槛；这类信息只供内部审核。
- `generated_reason`：必须与 `exposure_reason` 完全相同，作为旧版 Jev 管线的兼容字段。
- `evidence_fields`：只填写直接支撑曝光文案的字段路径，至少 2 个、最多 6 个，例如 `users.city`、`items.functions`、`items.suit_season`；逐字段回指文案，没有直接使用的商品类目、规格、功能、适用人群或地域字段，以及只用于选品的购物车、搜索词和标签，都不要填入。
- 最终回答只返回格式化 JSON：对象属性和数组元素使用换行与 2 个空格缩进，JSON 前后不添加英文过程说明、Markdown 或解释文字。
- 最终回答只能有一个 JSON 根对象；工具回显、过程进度、多个并列对象、未加引号的键、JSON5 写法和省略号都不属于最终 JSON。
- 调用工具前和工具调用之间不发送自然语言状态消息；工具轨迹只在 Harness 轨迹面板查看。
- 格式化检查是硬约束：第一行只有 `{`、最后一行只有 `}`，禁止返回单行压缩 JSON。
- `context_summary`：每条约 60 字以内的推荐依据总结。

### 空结果约定

当用户不存在、商品字段不足或找不到有事实支撑的推荐时：

```json
{
  "user_id": "u_9999",
  "recommendations": [],
  "context_summary": "users.csv 中无 u_9999，未生成推荐",
  "agent_version": "rec-agent-v2"
}
```

空结果时，固定 Schema 中只有 `recommendations` 内部才有 `context_summary`；为满足“说明原因”的要求，此处允许在**顶层**增加这一个 `context_summary` 字段。非空结果必须严格使用固定 Schema，不得出现顶层 `context_summary`。

## 职责边界

- 只负责选品和生成理由，不做曝光合规判决；不输出 `decision`、`risk_type`、`judge_score`、`escalated` 等字段。
- 不读取 `compliance_lexicon.txt` 或标签文件，避免生成端自我审查。
- 理由只能引用商品/用户/促销/场景的真实字段；不编造功能、功效、资质、优惠、销量或物流承诺。
- 生成结果本身就是 Jev 审核链路的候选输入，Agent 不声称结果已合规。

## 修改与重装

编辑 `cordis.patch.yml` 后，用 `plugin_manager` 的 `install_bundle` 重新安装本目录；profile 使用 `link:` 指向本目录，重装可让 Loader 重新读取最新声明。已存在的 Session 保留其启动时的插件修订，验证修改请新建 Session。

## 独立审核交接

Rec-Agent 不调用 Jev，也不通过终端启动审核脚本。生成完成后导出最终 JSON，由 Harness 外的 `scripts/run_recommendation_workflow.py` 接收。默认只准备事实与请求，显式 `--live` 才调用 Jev。该工作流也接受离线 canonical JSONL，无需启动 DeepSeek Harness。详见 [独立工作流](../docs/STANDALONE_WORKFLOW.md)。
