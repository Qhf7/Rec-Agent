# Jev API 接入配置说明

## 1. 已验证的接口

本项目实际验证通过的是 ModelGo 的 SystemOne 协议：

- Endpoint：`https://api.modelgo.ai/v1/systemone`
- Model：`jev-1.14.0`
- Authentication：`Authorization: Bearer $MODELGO_API_KEY`
- Content-Type：`application/json`

你提供的 `/v1/content_generation/tasks` 对 `jev-1.14.0` 返回了 `model_protocol_not_offered`，因此不作为 Jev 判决接口使用。

## 2. 环境变量

```bash
export MODELGO_API_KEY="<your-api-key>"
```

密钥只通过环境变量提供，不写入代码、Markdown、JSON、日志或 Git 提交。

## 3. SystemOne 请求格式

```json
{
  "model": "jev-1.14.0",
  "state": "{\\"reason_id\\":\\"r_0001\\",\\"generated_reason\\":\\"折叠收纳，卧室整理更方便\\"}",
  "questions": {
    "decision": {
      "type": "choice",
      "instructions": "请选择这条推荐理由的最终曝光处置结论。",
      "criteria": {
        "expose": "事实成立、无风险且可以直接曝光。",
        "rewrite": "存在可机械修复的问题，改写后可以曝光。",
        "human_review": "关键字段缺失、证据冲突或置信度不足，需要人工审核。",
        "block": "存在无法安全修复的风险，禁止曝光。"
      }
    },
    "risk_type": {
      "type": "choice",
      "instructions": "请选择主要风险类型。",
      "criteria": {
        "compliant": "事实成立且无风险。",
        "absolute_claim": "绝对化表达。",
        "efficacy_or_medical_claim": "功效或医疗宣称缺少依据。",
        "price_misleading": "价格或促销误导。",
        "missing_ai_disclosure": "缺少 AI 披露。",
        "off_topic": "与商品或用户语境无关。"
      }
    },
    "judge_score": {
      "type": "score",
      "instructions": "请评估这条理由的不安全概率，分数越高表示风险越高。",
      "criteria": [
        "低风险，概率接近 0。",
        "中风险，概率约为 0.5。",
        "高风险，概率接近 1。"
      ]
    }
  }
}
```

## 4. 本项目 Adapter

```text
JevAdapter.judge(fact_bundle) -> JevDecision
```

Adapter 位于：`jev_adapter.py`。

它负责：

- 构造 SystemOne 请求；
- 发送 HTTP 请求；
- 解析 `answers.decision`、`answers.risk_type` 和 `answers.judge_score`；
- 将 0/1/2 的评分量表归一化到 0~1；
- 由代码生成 `evidence`；
- 检查六类风险、四档处置和分数范围；
- 对 `unverifiable/conflict` 事实阻止直接 `expose`；
- 支持 dry-run 和本地测试。

## 5. 最小调用方式

先使用 dry-run：

```python
import json
from pathlib import Path
from jev_adapter import JevAdapter

bundle = json.loads(Path("fact_bundle.jsonl").read_text(encoding="utf-8").splitlines()[0])
preview = JevAdapter(dry_run=True).judge(bundle)
print(json.dumps(preview, ensure_ascii=False, indent=2))
```

真实调用前设置 `MODELGO_API_KEY`，并显式使用 `dry_run=False`。真实调用会消耗接口额度。

## 6. 安全要求

- 不在命令历史、代码、配置样例、日志和结果文件中打印密钥；
- 不把完整 Authorization Header 写入 `tool_trace`；
- 请求日志只记录 endpoint、模型名、状态码、耗时和请求哈希；
- 真实接口调用先使用单条脱敏事实包；
- 不关闭 TLS 证书校验；本项目在 Python CA 路径缺失时使用 `certifi` 证书链；
- 若密钥已在公开聊天、截图或日志中出现，应及时轮换。
