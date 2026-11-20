# Agent 评测与训练指南

本模块独立运行，不改变 Web 工作台或桌面 Harness 的线上推荐与 Jev 文案审核协议。当前结果见[评测结果](AGENT_EVALUATION.md)，任务状态见[进度](AGENT_ROADMAP.md)。

## 环境与数据

安装项目MCP依赖；模型联网调用读取进程中的 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 和 `MODELGO_API_KEY`。按[配置指南](WEB_UI.md)加载本机环境。
绘图另需 `pip install matplotlib`；学习式重排需 `pip install numpy`。本地训练完整依赖见后文。以下命令使用同一运行目录，首次执行前确保目录尚未存在。

```bash
python3 -m agent_benchmark.experiment freeze --output runs/agent-benchmark-v1/dataset
```

固定20个合成任务（开发12、留出8），用户隔离；包含12个显式构造对照，构造对照不作训练轨迹。清单记录任务及规范数据哈希。

## Agent执行

```bash
python3 -m agent_benchmark.runner --policy budgeted --split dev --output-dir runs/agent-benchmark-v1/dev-budgeted
python3 -m agent_benchmark.runner --policy adaptive --split dev --output-dir runs/agent-benchmark-v1/dev-adaptive
python3 -m agent_benchmark.experiment run --output runs/agent-benchmark-v1/matched-v2 --split holdout --ablations
```

每次使用新目录。`fixed`为固定查询后生成；`adaptive`自主选工具；`budgeted`加入观察压缩、调用/轮数/时间控制及信息齐备结束。三者工具上限均为任务的12次，最多8轮；不预留token，不限制累计token。`--max-tokens`只控制单次输出上限，默认4096。

模型请求与响应、原始工具结果、模型可见投影、provider usage和最终JSON分别保存。缺失usage记未知；失败任务留在完成率分母。`metrics.py`独立核验，不采信模型自报成功。

## 评审器对照

跨服务、Responses推理模型和档位回显处理见[三方评测与配置](MODEL_PROVIDER_COMPARISON.md)。

```bash
python3 -m agent_benchmark.judges --output runs/judge-controls --limit 12 --repeats 2 --workers 2
```

默认对冻结构造轨迹发起真实对照调用。`--traces`可指定JSON轨迹数组；双方使用相同可见观察及问题，未带程序参考答案。这里的三题评测任务完成、参数与事实覆盖，不等于生产文案审核两题。

对刚生成的24条真实留出轨迹进行同口径对照：

```bash
python3 - <<'PY'
from pathlib import Path
import json
root = Path('runs/agent-benchmark-v1')
traces = []
for policy in ('fixed', 'adaptive', 'budgeted'):
    for path in sorted((root / 'matched-v2' / ('holdout-' + policy)).glob('*/trace.json')):
        trace = json.loads(path.read_text())
        trace['trace_id'] = policy + '_' + trace['task_id']
        traces.append(trace)
(root / 'heldout-traces.json').write_text(json.dumps(traces, ensure_ascii=False))
PY
python3 -m agent_benchmark.judges --output runs/agent-benchmark-v1/judge-matched-final --traces runs/agent-benchmark-v1/heldout-traces.json --limit 24 --repeats 1 --workers 2
```

```bash
python3 -m agent_benchmark.report --run-root runs/agent-benchmark-v1 --judge-dir runs/agent-benchmark-v1/judge-matched-final --agent-root runs/agent-benchmark-v1/matched-v2
```

## 本地 LoRA

可选依赖：

```bash
pip install -r requirements-agent-training.txt
python3 -m agent_benchmark.training prepare --traces runs/agent-benchmark-v1/dev-budgeted runs/agent-benchmark-v1/dev-adaptive --output runs/agent-benchmark-v1/sft-data
python3 -m agent_benchmark.training train --data runs/agent-benchmark-v1/sft-data --output runs/agent-benchmark-v1/sft-adapter --max-steps 8 --rank 4 --max-seq-length 2048
python3 -m agent_benchmark.training evaluate --adapter runs/agent-benchmark-v1/sft-adapter --output runs/agent-benchmark-v1/sft-evaluation --limit 8 --max-seq-length 2048
```

模型 `Qwen/Qwen2.5-0.5B-Instruct` 需提前缓存；训练只读本地权重，不自动下载。准备阶段复核真实开发轨迹、执行来源和用户隔离；超长输入排除，assistant动作及EOS参与loss。单步工具诊断与完整任务完成率分别报告。

完整任务对照可通过 `LocalActionClient` 注入同一执行器（同样2个任务、相同参数分别跑base与LoRA）：

```python
from agent_benchmark.dataset import build_tasks
from agent_benchmark.runner import run_task
from agent_benchmark.metrics import evaluate_trace
from agent_benchmark.training import LocalActionClient

tasks = [t for t in build_tasks() if t['task_id'] in ('holdout_001', 'holdout_003')]
for label, adapter in [('base', None), ('lora', 'runs/agent-benchmark-v1/sft-adapter')]:
    client = LocalActionClient(adapter_path=adapter, max_input_tokens=2048, max_new_tokens=256)
    for task in tasks:
        trace = run_task(task, 'budgeted', client=client, max_model_calls=4, max_tool_calls=12,
                         max_seconds=90, max_tokens=256,
                         output_dir=f"runs/agent-benchmark-v1/student-e2e/{label}/{task['task_id']}")
        print(label, evaluate_trace(task, trace))
```

## 检索与偏好数据

```bash
python3 -m agent_benchmark.retrieval --output-dir runs/retrieval
python3 -m agent_benchmark.retrieval --learned --output-dir runs/retrieval-learned
python3 -m agent_benchmark.preferences prepare --run-root runs/agent-benchmark-v1 --output runs/preferences
```

检索只用明确偏好和搜索；购物车仅为弱标签，未标注用户不作零分。`--learned` 在开发用户上拟合线性Pairwise重排器，不能读取留出标签拟合。偏好表默认留空，由标注者选择A/B或tie，校验来源哈希后才能导出训练对。当前没有人工标签，未进行DPO。

## 验证

```bash
python3 -m pytest -q
node --test tests/static-api.test.js
```

运行产物、适配器、凭据不提交。公开结果必须分别说明样本数、独立用户数、调用次数、失败分母、标签来源与计数缺失。
