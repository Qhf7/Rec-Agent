# 数据层说明（Mock）

> 全部数据为虚构，**不含任何真实用户、商品、品牌或交易数据**。用于跑通「生成 → 判决 → 回放」链路，不能用于真实业务结论。
>
> 场景日期：`2026-06-15`（杭州梅雨季，便于生成「梅雨季防潮」类理由与原型的上下文校验）
> 生成脚本：`scripts/gen_data.py`（固定随机种子 `20260615`，可复现）
> 校验脚本：`scripts/validate_data.py`

---

## 1. 文件清单

| 文件 | 内容 | 规模 |
|---|---|---|
| `raw/users.csv` | 用户画像与行为快照 | 200 |
| `raw/items.csv` | 商品结构化属性、价格、优惠、合规标记 | 200 |
| `raw/promo_rules.json` | 满减/折扣/券/赠品规则 | 30（22 生效 / 4 已结束 / 4 未开始） |
| `raw/compliance_lexicon.txt` | 绝对化/功效/医疗/价格词表 | 45 |
| `raw/lexicon_variants.tsv` | 谐音、拼音、繁体、英文等变体 | 20 |
| `raw/history_reason_stats.csv` | 同类理由历史表现（pattern 级） | 30 |
| `exposure_click_history.csv` | 按推荐理由拆分的日粒度曝光点击历史（模拟） | 4,200 |
| `recommendation_feedback_history.csv` | Jev 通过后的一次推荐曝光/点击事件（模拟） | 1,600 |
| `raw/city_climate.json` | 城市/气候区/梅雨季映射 | 12 城市 |
| `mock.db` | 上述数据的 SQLite 版本，供 MCP 工具直接查询 | — |

候选与曝光评测产物按批次生成：`reason_candidates.jsonl`、`exposure_log.jsonl`、`labels.csv`、`latent.csv`。`exposure_click_history.csv` 是基于全量 300 条候选与 14 天观察窗生成的统计回放数据，不替代原始曝光汇总；`recommendation_feedback_history.csv` 是给 Rec-Agent 读取的事件级模拟反馈，一行代表一次已通过 Jev 且已展示的推荐，含 `event_time`、`clicked`、`click_time`、位置、流量来源、设备和会话字段。

---

## 2. 编码约定

- **金额**：一律用「分」为单位的整数（`price_cents=3990` 表示 ¥39.90），避免浮点误差。
- **列表字段**：CSV 内用 `|` 分隔；SQLite 内是 JSON 数组字符串（如 `["折叠","防尘"]`），工具层解析后使用。
- **布尔字段**：CSV 内是 `true`/`false`；SQLite 内是 `1`/`0`。
- **ID**：`u_0001..u_0200`、`i_0001..i_0200`、`P001..P030`、`HS01..HS30`。
- **CSV 编码**：UTF-8 with BOM（Excel 直接打开不乱码）。
- **时间**：`YYYY-MM-DD`；没有真实时钟，`get_session_context` 以 `2026-06-15` 为基准。

---

## 3. 用户表关键字段

| 字段 | 说明 | 用途 |
|---|---|---|
| `city` / `city_tier` / `climate_zone` | 城市、线级、气候区 | 地域/季节语境校验 |
| `age` / `gender` / `life_stage` | 18–55 岁；学生/单身职场/新婚/新手妈妈/新手爸爸/学龄家长/空巢 | 人群适配 |
| `member_level` / `account_age_days` / `account_status` | normal/88VIP；账户年龄；normal/risk_control/limited | 权益与账户风险 |
| `consumption_level` / `aov_90d` / `orders_90d` | L1–L5；近 90 天客单价与订单数 | 价格带匹配 |
| `price_sensitivity` | high/mid/low | 文案风格 |
| `preferred_categories` | 2–3 个一级类目 | 召回与排序 |
| `night_owl` / `active_hours` | 是否深夜活跃；活跃时段 | 时段策略 |
| `recent_cart_item_ids` / `recent_order_item_ids` | 购物车/订单商品 ID（外键到 items） | 行为上下文 |
| `last_search_terms` | 1–3 个搜索词 | 意图 |
| `tags` | 2–4 个标签（租房/养猫/有娃/预算敏感…） | 个性化理由素材 |

**实际分布**：12 城市（杭州 34、上海 26、北京 20、广州 19…）；深夜活跃 15%；新账户 11%；异常账户 7.5%；88VIP 19%。

---

## 4. 商品表关键字段

| 字段 | 说明 | 用途 |
|---|---|---|
| `category_l1/l2/l3` | 8 个一级类目 × 35 个二级类目 | 类目匹配、敏感类目 |
| `functions` | 结构化功能，如 `折叠/防尘/收纳` | **功效支持判断的核心字段** |
| `material` / `spec` / `suit_audience` / `suit_season` | 材质、规格、适用人群、季节 | 事实核验 |
| `efficacy_claims_allowed` | 允许的功效宣称（仅特殊类目） | 判断「宣称是否超范围」 |
| `qualifications` | 妆字号/械字号/蓝帽子/3C/GB 标准/无 | 功效宣称的资质前提 |
| `price_cents` / `original_price_cents` | 现价/划线价 | 价格核验 |
| `promo_tags` / `promo_rule_ids` | 可读优惠名/规则 ID | 优惠核验 |
| `stock` / `sales_30d` / `rating` | 库存/销量/评分 | 质量先验（进入曝光 DGP） |
| `return_rate_30d` / `complaint_rate_30d` | 退货率/投诉率基线 | 质量先验 |
| `regulated_category` | general/food/cosmetic/health_food/medical_device/children | 合规强度 |
| `sensitive_category` | 是否敏感类目 | 是否强制人审 |
| `ad_law_notes` | 该类目的合规提示 | 证据/解释辅助 |

**实际分布**：8 个一级类目各 25 条；敏感类目 65 条（32.5%）；优惠覆盖 144 条（72%）；价格 ¥30.9–¥467.9；15 条库存为 0（用于测「缺货仍被推荐」）。

### 敏感类目与资质对应

| regulated_category | 数量 | 资质 | 允许宣称（示例） |
|---|---|---|---|
| `cosmetic` | 25 | 妆字号 | 清洁、保湿、控油、显色 |
| `children` | 25 | 3C / GB15979 / GB31701 / GB4806 | 无（不得宣称医疗功效） |
| `medical_device` | 10 | 械字号 | 测量血压、牵引、支撑 |
| `health_food` | 5 | 蓝帽子 | 补充维生素C |
| `food` | 30 | SC | 无（不得宣称保健/治疗） |
| `general` | 105 | 无 | 物理功能（折叠、收纳、送风…） |

> 注意：`health_food` 只有 5 条，做分型评测时样本偏少；如果后面需要更细的保健类分析，可以在 `gen_data.py` 里把维生素C 的 5 个变体扩成更多类型，或把蛋白粉归到 `health_food`（当前归 `food`，更符合「普通食品」的实际口径）。

---

## 5. 优惠规则

`promo_rules.json` 是数组，每条包含：

```json
{
  "rule_id": "P003",
  "type": "full_reduction",
  "title": "食品生鲜满99减10",
  "threshold_cents": 9900,
  "discount_cents": 1000,
  "discount_percent": 0,
  "gift": "",
  "scope": {"category_l1": ["食品生鲜"]},
  "start": "2026-06-01",
  "end": "2026-06-30",
  "stackable": false,
  "fine_print": "不与会员折扣、其他优惠叠加"
}
```

- `type`：`full_reduction` / `discount` / `coupon` / `gift`。
- 折扣用 `discount_percent=85` 表示 85 折（不是 85% off）。
- 商品上的 `promo_rule_ids` 只挂**当前生效**的规则；已结束/未开始的规则保留在规则表里，用于构造「文案提了不存在的优惠」类样本。
- 当前生效 22 条（`2026-06-01`～`2026-06-30`），已结束 4 条（5 月），未开始 4 条（7 月）。

---

## 6. 词表与变体

`compliance_lexicon.txt` 每行：

```
term|canonical|risk_type|severity|law_ref|note
```

例：

```
防潮|防潮|efficacy_or_medical_claim|high|广告法第28条|功能宣称需属性支撑
治疗|治疗|efficacy_or_medical_claim|critical|广告法第17条|医疗用语
```

- 45 条：绝对化 15、功效 18、医疗 5、价格 7。
- `law_ref` 是教学口径，不构成法律意见。
- 变体表 `lexicon_variants.tsv`：`variant\tcanonical\ttype`，用于归一化后再匹配（如 `蕞→最`、`zui→最`、`NO.1→第一`）。

---

## 7. 历史表现

`history_reason_stats.csv` 是 **pattern 级**（类目 × 钩子类型）的历史汇总，不是单条理由：

| 字段 | 说明 |
|---|---|
| `pattern_id` | HS01–HS30 |
| `category_l2` | 二级类目 |
| `hook_type` | 季节/地域/人群/价格/场景/功效/情绪 |
| `ctr` / `refund_rate` / `complaint_rate` / `block_rate` | 历史表现 |
| `n` | 样本量 |

用途：给判决层提供「同类理由先验」，辅助校准；**不直接作为违规证据**，且不能与当前候选的标签混用（防泄漏）。

`recommendation_feedback_history.csv` 只供 Rec-Agent 做用户历史参考。它不进入 Jev 输入；真实链路应在最终 Jev 通过并完成展示后写入，点击与未点击都要记录。MCP 返回的 `smoothed_ctr` 使用弱先验抑制小样本波动。没有个人事件时，Agent 进入 `cold_start`，回退到画像、购物车、搜索词、时段和类目先验。

---

## 8. 重建与校验

```bash
python3 scripts/gen_data.py      # 重新生成全部 CSV/JSON/SQLite
python3 scripts/validate_data.py # 7 类硬校验 + 分布告警
python3 generate_exposure_click_history.py # 生成日粒度曝光点击参考数据
python3 scripts/generate_recommendation_feedback_history.py # 生成 Agent 可读的事件级反馈参考数据
```

校验覆盖：数量/唯一性/外键/类目/资质/价格/库存/评分/促销规则/用户字段/敏感比例/优惠覆盖/DB 行数。

当前结果：

```
counts: {'users': 200, 'items': 200, 'rules': 30, 'active_rules': 22,
         'lexicon': 45, 'variants': 20, 'history': 30}
ratios: {'sensitive': 0.325, 'promo': 0.72, 'night_owl': 0.15,
         'new_user': 0.11, '88vip': 0.19, 'abnormal': 0.075}
PASS: all hard checks passed
```

---

## 9. 常用查询

```sql
-- 某用户画像
SELECT * FROM users WHERE user_id = 'u_0007';

-- 某类目下可推荐商品
SELECT item_id, title, price_cents, functions
FROM items
WHERE category_l1 = '家居日用' AND stock > 0
ORDER BY sales_30d DESC
LIMIT 10;

-- 含某功能词的商品
SELECT item_id, title, functions
FROM items
WHERE functions LIKE '%防潮%';

-- 当前生效的优惠规则
SELECT rule_id, title FROM promo_rules
WHERE start <= '2026-06-15' AND end >= '2026-06-15';

-- 词表命中
SELECT term, risk_type, severity FROM lexicon
WHERE term IN ('防潮', '最', '治疗');
```

---

## 10. 已知局限

1. **虚构品牌**：所有品牌/商品均为生成，不能用于真实商誉或法务判断。
2. **类目均衡**：8 个一级类目各 25 条，是刻意均衡，不是真实电商的长尾分布。
3. **健康类样本少**：`health_food` 仅 5 条，做细分型评测时置信区间会很宽。
4. **价格为模拟**：划线价按 1.25–1.8 倍生成，不代表真实价格行为。
5. **行为快照**：购物车/订单是静态 ID 列表，没有时间序列；深夜/时段只做静态标记。
6. **天气是规则生成**：`city_climate.json` 只提供季节/梅雨标记，不接真实天气 API。
7. **没有真实标签**：候选理由、曝光日志、人工标签和推荐反馈均为合成参考数据，不能替代线上埋点或人工金标。
