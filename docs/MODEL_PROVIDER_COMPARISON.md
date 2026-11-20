# 六模型评测、官方价格与 Jev 判断对照

## 具体模型及思考设置

| 展示模型 | 实际API模型标识 | 思考设置与观测 |
| --- | --- | --- |
| **DeepSeek V4.1 Flash** | `deepseek-v4.1-flash-1017`，响应 `deepseek-v4-1-flash-261017` | **Max**：启用thinking并传reasoning_effort=max；24次均有推理token |
| **Jev 1.14.0** | `jev-1.14.0` | 专用判决模型，不设通用推理等级 |
| **ChatGPT 6.1 Sol** | `gpt-6.1-sol` | **xhigh**，请求与响应档位一致 |
| **Kimi K3.1 Pro** | 接入 `kimi-k3.1-pro-zbs`，响应 `kimi-k3.1-pro` | 思考开启；配置max，响应不回显具体档位 |
| **Claude Opus 5.5** | `claude-opus-5.5` | 服务默认；未提供可核验等级或推理token明细 |
| **Qwen3.8-Max** | `qwen3.8-max` | 思考开启，实际返回推理token；模型名Max不是reasoning_effort等级 |

DeepSeek本轮为重新发起的Max实测。通用模型单次输出额度16384，Jev使用专用接口；不预留token，也不设置累计token门槛。

## 两组独立对照

1. **Agent轨迹三题**：同24条冻结轨迹（8个任务标识×3策略）×6模型，共144请求，比较任务完成、参数有效、事实覆盖的程序契约判断。
2. **商品理由两题**：同13个案例ID×6模型，共78请求，对比风险类别、吸引力及最终曝光/改写；包含重复内容条件，逐条见[文案审核分析](JEV_MODEL_JUDGMENT_COMPARISON.md)。

各组均固定种子交错、并发2，无自动重试。两组同时运行时全局最多4个客户端在途请求；因此延迟是该共同实验负载下的服务观测，不是隔离环境性能上限。线上Harness与独立Jev审核架构保持不变。

## Agent轨迹评审结果

所有模型收到相同可见观察、问题和商品事实，case哈希与最初冻结清单一致，未发送程序参考标签。

| 模型 | 有效回答 | 任务判断一致 | 参数判断一致 | 事实覆盖判断一致 | P95延迟 | 平均延迟 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DeepSeek V4.1 Flash · **Max** | 24/24 | 23/24（95.8%） | 24/24（100%） | 23/24（95.8%） | 20.71秒 | 9.38秒 |
| Jev 1.14.0 | 24/24 | 21/24（87.5%） | 22/24（91.7%） | 24/24（100%） | **0.92秒** | **0.64秒** |
| ChatGPT 6.1 Sol · xhigh | 24/24 | 24/24（100%） | 24/24（100%） | 22/24（91.7%） | 22.35秒 | 12.16秒 |
| Kimi K3.1 Pro · 思考开启 | 24/24 | 23/24（95.8%） | 24/24（100%） | 23/24（95.8%） | 61.45秒 | 21.63秒 |
| Claude Opus 5.5 · 服务默认 | 24/24 | 24/24（100%） | 24/24（100%） | 24/24（100%） | 9.96秒 | 6.88秒 |
| Qwen3.8-Max · 思考开启 | 24/24 | 24/24（100%） | 24/24（100%） | 24/24（100%） | 81.29秒 | 39.37秒 |

![六模型轨迹评审与官方价成本](assets/provider-comparison/comparison.png)

“一致”是与可执行契约核验一致，不是独立人工语义准确率。当前参数参考全部all_valid，事实覆盖只含full/partial，不能由此估计invalid参数或零覆盖检出率。Claude和Qwen在本批三题全匹配，但只24轨迹、8个相互关联任务，不能外推为普遍满分。

| 模型 | 平均评审API调用数 | 平均输入token | 平均输出token（含已计量推理） | 其中平均推理token |
| --- | ---: | ---: | ---: | ---: |
| DeepSeek V4.1 Flash · Max | 1 | 5158.67 | 1154.08 | 1105.50 |
| Jev 1.14.0 | 1 | 7315.92 | 102.00 | 未提供 |
| ChatGPT 6.1 Sol · xhigh | 1 | 5139.75 | 262.54 | 203.92 |
| Kimi K3.1 Pro · 思考开启 | 1 | 4838.54 | 964.00 | 909.79 |
| Claude Opus 5.5 · 服务默认 | 1 | 7720.71 | 311.29 | 未提供 |
| Qwen3.8-Max · 思考开启 | 1 | 5243.58 | 1784.71 | 1733.67 |

这轮评审的是冻结轨迹，各评审器每条轨迹只调用一次，不重新执行工具。Agent本身的任务完成率、工具调用数和事实覆盖实测见[Agent执行评测](AGENT_EVALUATION.md)。不同服务的token计数口径不同，费用使用下述各模型费率折算；未提供推理计数不代表没有推理。

## 各模型与 Jev 的轨迹判断差异

| 模型 | 三题整份完全一致 | 任务题一致 | 参数题一致 | 覆盖题一致 |
| --- | ---: | ---: | ---: | ---: |
| DeepSeek V4.1 Flash · Max | 18/24 | 20/24 | 22/24 | 23/24 |
| ChatGPT 6.1 Sol · xhigh | 18/24 | 21/24 | 22/24 | 22/24 |
| Kimi K3.1 Pro | 18/24 | 20/24 | 22/24 | 23/24 |
| Claude Opus 5.5 | 19/24 | 21/24 | 22/24 | 24/24 |
| Qwen3.8-Max | 19/24 | 21/24 | 22/24 | 24/24 |

该表以Jev为比较对象，不把Jev当正确答案，程序参考单独用于定位差异：

- `adaptive_holdout_002/004`：Jev认为存在无效工具参数，其余模型认为全部有效；独立参数校验支持后者。工具恢复/执行异常不能自动视为参数错误。
- `adaptive_holdout_008`、`budgeted_holdout_001/003`：Jev判断未完成，其余模型判断完成，程序契约也确认完成。这里表现为Jev对任务完成较保守。
- `fixed_holdout_006`：DeepSeek Max、Kimi认为未完成且覆盖不足，Jev认为完成并完整覆盖；程序参考支持Jev，不能把“与Jev不同”一律视为Jev出错。
- ChatGPT在`adaptive_holdout_008`与`budgeted_holdout_004`判覆盖partial，而Jev及程序参考为full；覆盖按明确任务事实组计算，模型可能加入额外信息要求。

逐项差异含双方答案、程序参考及输入哈希：[jev-agreement.json](assets/provider-comparison/jev-agreement.json)。此处差异定位基于保存答案与程序核验，不推测模型隐藏思考。

## 官方单价与成本

新模型费率核验日期：2026-11-21；其他模型沿用已保存的2026-11-20官方快照。单位为美元／百万token，按标准实时短上下文，不含税、批量或加速服务档。

| 模型 | 普通输入 | 缓存命中输入 | 输出 | 缓存写入 | 官方来源 |
| --- | ---: | ---: | ---: | --- | --- |
| DeepSeek V4.1 Flash：峰时基准 | $0.30 | $0.006 | $1.20 | 无单独费用 | [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing) |
| Jev 1.14.0 | $0.042 | $0.042（统一输入费） | $0 | 无单独缓存档 | [TypeSafe](https://docs.typesafe.ai/models) |
| ChatGPT 6.1 Sol | $2.00 | $0.10 | $10.00 | 30分钟$2.50／12小时$5 | [OpenAI](https://developers.openai.com/api/docs/pricing) |
| Kimi K3.1 Pro | $2.00 | $0.20 | $10.00 | 5分钟$2／1小时$4 | [Kimi](https://platform.kimi.ai/docs/pricing/chat) |
| Claude Opus 5.5 | $4.00 | $0.20 | $20.00 | 5分钟$5／1小时$8 | [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) |
| Qwen3.8-Max：International | $2.00 | $0.40（隐式缓存） | $6.00 | 隐式写入按普通输入价 | [阿里云单价](https://www.alibabacloud.com/help/en/model-studio/model-pricing)／[缓存规则](https://www.alibabacloud.com/help/en/model-studio/context-cache) |

Qwen采用新加坡International美元价作为统一基准；Global官方情景为输入$1.650、输出$4.951。中转上游地域与计费方式不能由模型标识确认，因此这不是实付账单。Qwen本轮没有请求显式缓存，按隐式命中20%输入价折算，不误用显式缓存10%规则。

**每千次轨迹评审的官方价等效成本**：六家本轮24case均有计量，主表使用完全相同24个case。冷缓存列把全部逻辑输入视为cache miss，不计新建缓存；第二列保留实际缓存优惠与缺失计量区间。

| 模型 | 统一冷缓存 USD／千次 | 按报告缓存折算 USD／千次 |
| --- | ---: | ---: |
| DeepSeek V4.1 Flash · Max | $2.9325 | $2.9325 |
| Jev 1.14.0 | **$0.3073** | **$0.3073** |
| ChatGPT 6.1 Sol · xhigh | $12.9049＊ | $12.8961＊ |
| Kimi K3.1 Pro | $19.3171 | $19.1528–$25.7662 |
| Claude Opus 5.5 | $37.1087 | $36.1878–$38.0780 |
| Qwen3.8-Max · International | $21.1954 | $20.7176 |

＊ChatGPT本轮12/24条usage明确带estimated，其他12条未标注，不能据“未标注”认定为已核验原生账单。所有金额都是官方价乘接口用量的等效估算，不是第三方实际扣费。

![缓存假设下的成本对照](assets/provider-comparison/cost-assumptions.png)

- 推理token已经在输出计数中，不重复收费。成本按输入、输出、命中、写入分别计算，不比较裸token大小。
- DeepSeek本轮均未命中缓存，按峰时基准$2.9325／千次；谷时情景为$1.4663／千次。本次调用时段处于官方谷时，峰时只作标准化比较。
- Kimi缺失命中计量或写入TTL时保留区间，不能假设免费或零命中。
- Claude一条响应同时报告cache read为0、cached_tokens为5808、cache creation为5808，而输入总量5816；缓存细项互相矛盾。本次缓存成本对该条按所有公布输入档位取保守区间，不擅自选字段；冷缓存仅依赖有效输入总量与输出总量，仍可计算。
- Jev在本轮两种成本口径均最低，但历史高缓存命中实验DeepSeek曾更低，不能宣传为所有缓存场景绝对最便宜。Qwen Global情景等费率变体保留在配置中，不与主表混算。

在本轮共同24条轨迹上，Jev的P95延迟为其余模型的约1/10.9至1/88.8，统一冷缓存官方价等效成本为约1/9.5至1/120.8；这两项是本批实测支持的优势。任务完成与参数判断一致性则低于部分通用模型，适合结合明确契约使用，不能由速度或价格推导判断质量全面领先。

## 商品理由的实际风险、评分与处置

除上述轨迹评审，还完成13案例×6模型共78次生产两题审核。[完整逐条表格与分析](JEV_MODEL_JUDGMENT_COMPARISON.md)包括：

- 明确风险在有效答复中大体一致；正常抽纸文案的三处处置差异主要来自Jev低于50分的吸引力评分。
- 候选提示注入文本的风险类别存在差异，但全部有效结果均改写，没有被要求满分通过。
- Claude 3/13答案带代码围栏，严格JSON解析失败；未静默修复，不计入有效答卷。
- Jev的概率期望分与通用模型的离散等级共享锚点但校准不同，分差不能直接解释为审核能力差距。

## 复现与记录

```bash
python3 -m agent_benchmark.providers --manifest runs/agent-benchmark-v1/judge-matched-final/manifest.json --config-file examples/evaluator_providers.json --output runs/provider-comparison --workers 2 --repeats 1 --timeout 180
python3 -m agent_benchmark.provider_report --run runs/provider-comparison --output runs/provider-comparison/figures --prices examples/official_model_prices.json
python3 -m agent_benchmark.judgment_comparison --config-file examples/evaluator_providers.json --output runs/advertising-judgments --workers 2 --limit 13
python3 -m agent_benchmark.judgment_report --run runs/advertising-judgments --output runs/advertising-judgments/figures
```

[逐例轨迹答卷](assets/provider-comparison/case-results.json) · [质量/成本汇总](assets/provider-comparison/summary.json) · [共同case成本](assets/provider-comparison/paired-costs.json) · [费率配置](../examples/official_model_prices.json)

凭据均为独立环境变量；Claude与Jev共用ModelGo服务，Qwen单独读取QWEN_API_KEY，不覆盖推荐端DeepSeek凭据。原始响应、价格快照和敏感配置保留本机忽略目录，公开工件不含密钥。供应商模型标识及推理元数据描述接口观测，不独立证明底层权重身份。
