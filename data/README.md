# 数据说明

本目录提供可复现的合成用户、商品、场景和反馈数据，供推荐、审核与交互演示使用。数据不包含真实用户或交易记录，也不代表线上业务表现。

## 数据目录

[`raw/`](raw/) 是 MCP、离线候选和事实包共用的规范数据源；[`canonical_data.py`](../canonical_data.py) 负责读取、归一化和契约校验。

| 文件 | 内容 |
| --- | --- |
| [raw/users.csv](raw/users.csv) | 200 条用户画像、偏好、搜索词和购物车快照 |
| [raw/items.csv](raw/items.csv) | 200 条商品的类目、功能、材质、价格、库存与资质 |
| [raw/promo_rules.json](raw/promo_rules.json) | 促销条件、适用范围与有效期 |
| [raw/city_climate.json](raw/city_climate.json) | 城市、气候区与季节场景 |
| [raw/compliance_lexicon.txt](raw/compliance_lexicon.txt) | 风险词及分类参考 |
| [raw/lexicon_variants.tsv](raw/lexicon_variants.tsv) | 词语变体与标准词映射 |
| [raw/history_reason_stats.csv](raw/history_reason_stats.csv) | 类目与文案类型的合成统计先验 |
| [recommendation_feedback_history.csv](recommendation_feedback_history.csv) | 事件级推荐曝光与点击记录 |
| [exposure_click_history.csv](exposure_click_history.csv) | 日粒度曝光、点击、加购与下单参考数据 |
| [mock.db](mock.db) | 基础数据的 SQLite 副本 |

## 统一契约

| 约定 | 格式 |
| --- | --- |
| 用户 / 商品 ID | `u_####` / `i_####` |
| 商品类目 | `category_l1`、`category_l2`、`category_l3` |
| 商品价格 | `price_cents`、`original_price_cents`，整数分 |
| CSV 列表 | 使用 `\|` 分隔；工具返回 JSON 数组 |
| CSV 布尔值 | `true` / `false` |
| 日期 / 时间 | `YYYY-MM-DD` / 带时区的 ISO 8601 时间 |
| 默认场景日期 | `2026-06-15`，时区 `Asia/Shanghai` |

商品事实主要包含 `functions`、`material`、`spec`、`suit_audience`、`suit_season`、`efficacy_claims_allowed` 和 `qualifications`。促销规则同时记录门槛、折扣、范围和有效期，使用时须与商品及场景日期匹配。

用户数据主要包含地域、兴趣类目、标签、价格偏好、搜索词、购物车和订单快照。完整字段以 CSV 表头为准。

## 推荐反馈

`recommendation_feedback_history.csv` 每行模拟一次通过审核并展示的推荐，记录用户、商品、曝光理由、推荐时间、是否点击、点击时间、展示位置、设备和会话信息。

反馈历史仅供 Rec-Agent 选品与生成推荐时参考，**不传入 Jev**。没有个人反馈时，推荐依据画像、搜索词、购物车和场景信息进行冷启动。当前数据由脚本合成，实际曝光与点击采集需由业务系统接入。

## 生成与校验

在项目根目录执行：

```bash
python3 scripts/gen_data.py
python3 scripts/validate_data.py
python3 generate_exposure_click_history.py
python3 scripts/generate_recommendation_feedback_history.py
```

生成命令会覆盖对应数据文件；请在执行前保存自定义数据。生成器使用固定随机种子，便于复现。

[返回项目首页](../README.md)
