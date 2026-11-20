# 曝光理由参考语料

本目录包含 300 条合成文案，覆盖 12 类句型和 60 个示例商品，供文案句式检索与提示词参考。语料参考公开报道中的信息流表达方式编写，不属于平台抓取数据或人工审核金标。

## 文件

| 文件 | 内容 |
| --- | --- |
| [exposure_reasons_300.csv](exposure_reasons_300.csv) | 可用于表格筛选的语料 |
| [exposure_reasons_300.jsonl](exposure_reasons_300.jsonl) | 每行一条的结构化语料 |
| [stats.json](stats.json) | 句型、人称和类目分布 |
| [build_corpus.py](build_corpus.py) | 语料构建脚本 |

## 字段

| 字段 | 含义 |
| --- | --- |
| `id` / `text` | 语料编号与文本 |
| `pattern` / `person` | 句型与人称 |
| `category` / `product` | 示例类目与商品短名 |
| `length` | 含标点的字符数 |
| `needs_fields` | 支撑文案所需事实的参考标记 |
| `risk_level` / `note` | 风险提示与核验要点 |

使用前需按实际商品事实筛选文案，并将 `needs_fields` 映射到项目的规范字段。语料包含参数、促销和功效等不同表达，不能直接作为推荐输出、事实证据或审核标签。

## 公开参考来源

[《淘宝推荐系统的革命性升级：RecGPT 如何让购物变得更智能》](https://www.sohu.com/a/921529864_114765)（至顶头条，2025-08-07）转述了 [RecGPT 论文](https://arxiv.org/abs/2507.22879) 中的推荐案例，包括“夏日穿搭清爽有型”“水温测量让妈妈更安心”等表达。该来源用于句型参考，合成语料的内容与分布由本项目构造。

## 构建

在项目根目录执行：

```bash
python3 corpus/build_corpus.py
```

脚本生成 CSV、JSONL 和统计文件。

[返回项目首页](../README.md)
