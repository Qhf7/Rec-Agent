"""Freeze tasks or execute an interleaved, matched-budget Agent experiment."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random

from agent_benchmark.dataset import build_tasks, freeze_dataset
from agent_benchmark.metrics import evaluate_trace
from agent_benchmark.runner import run_task
from agent_benchmark.report import summarize_traces


def run(output: Path, *, split: str = "holdout", include_ablations: bool = False) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    tasks = [t for t in build_tasks() if t["split"] == split]
    variants = {"fixed": ("fixed", {}), "adaptive": ("adaptive", {}), "budgeted": ("budgeted", {})}
    if include_ablations:
        variants.update(no_compression=("budgeted", {"compact_observations": False}),
                        no_early_finish=("budgeted", {"early_finish": False}))
    jobs = []
    for index, task in enumerate(tasks):
        names = list(variants) if index < 4 else ["fixed", "adaptive", "budgeted"]
        random.Random(20261120 + index).shuffle(names)
        jobs.extend((task, name) for name in names)
    code = ["runner.py", "metrics.py", "tools.py", "dataset.py"]
    manifest = {"seed": 20261120, "split": split, "task_count": len(tasks), "workers": 1,
                "max_tool_calls": 12, "max_model_calls": 8, "token_budget": None, "token_reserve": None,
                "response_output_cap": 4096, "component_ablation_tasks": [t["task_id"] for t in tasks[:4]] if include_ablations else [],
                "code_sha256": {f: hashlib.sha256(Path(__file__).with_name(f).read_bytes()).hexdigest() for f in code},
                "schedule": [(t["task_id"], n) for t, n in jobs]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    for task, name in jobs:
        policy, options = variants[name]
        dest = output / (split + "-" + name) / task["task_id"]
        trace = run_task(task, policy, output_dir=dest, max_tool_calls=12, **options)
        metric = evaluate_trace(task, trace)
        (dest / "metrics.json").write_text(json.dumps(metric, ensure_ascii=False, indent=2))
        print(json.dumps({"task_id": task["task_id"], "policy": name, "completed": metric["task_completed"]}), flush=True)
    results = {name: summarize_traces(output / (split + "-" + name)) for name in variants}
    (output / "aggregate.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("dev", "holdout"), default="holdout")
    parser.add_argument("--ablations", action="store_true")
    args = parser.parse_args()
    result = freeze_dataset(args.output) if args.command == "freeze" else run(args.output, split=args.split, include_ablations=args.ablations)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
