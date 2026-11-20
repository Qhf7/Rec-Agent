"""Summarize real trace metrics and matched judge comparisons without relabeling."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path

from agent_benchmark.judges import percentile


def summarize_traces(directory: Path) -> dict:
    from agent_benchmark.dataset import build_tasks
    from agent_benchmark.metrics import evaluate_trace
    tasks = {t["task_id"]: t for t in build_tasks()}
    traces = [json.loads(p.read_text()) for p in sorted(Path(directory).glob("*/trace.json"))]
    if not traces:
        raise ValueError("no traces")
    metrics = [evaluate_trace(tasks[t["task_id"]], t) for t in traces]
    n = len(traces)
    valid, attempted = sum(m["valid_tool_calls"] for m in metrics), sum(m["attempted_tool_calls"] for m in metrics)
    required, covered = sum(m["required_fact_count"] for m in metrics), sum(m["covered_fact_count"] for m in metrics)
    result = {"tasks": n, "completed": sum(m["task_completed"] for m in metrics),
              "task_completion_rate": sum(m["task_completed"] for m in metrics) / n,
              "valid_tool_calls": valid, "attempted_tool_calls": attempted,
              "tool_parameter_accuracy": valid / attempted if attempted else None,
              "fact_coverage": covered / required if required else None,
              "mean_model_calls": sum(len(t["model_calls"]) for t in traces) / n,
              "mean_tool_calls": attempted / n,
              "p95_latency_seconds": percentile([t["duration_seconds"] for t in traces]),
              "errors": sum(bool(t.get("error")) for t in traces),
              "budget_stops": sum(bool(t.get("budget_exceeded")) for t in traces)}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
        values = [t["usage"].get(key) for t in traces]
        known = [v for v in values if v is not None]
        result[key] = {"reported_tasks": len(known), "total_tasks": n,
                       "sum_reported": sum(known) if known else None,
                       "mean_reported": sum(known) / len(known) if known else None}
    result["per_task"] = [{"task_id": t["task_id"], "scenario": tasks[t["task_id"]]["scenario"],
                           "split": tasks[t["task_id"]]["split"], "completed": m["task_completed"],
                           "fact_coverage": m["fact_coverage"], "errors": m["errors"]}
                          for t, m in zip(traces, metrics)]
    return result


def charts(judge: dict, agents: dict, output: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})
    output.mkdir(parents=True, exist_ok=True)
    colors = ["#8d7be8", "#48ae9a"]
    evaluators = judge["evaluators"]
    labels = ["General LLM", "Jev"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), layout="constrained")
    for ax, key, title in zip(axes, ("answer_success_rate", "p95_latency_seconds", "total_tokens"),
                               ("Valid responses (%)", "P95 judge latency (s)", "Mean reported tokens")):
        values = [evaluators[k][key]["mean_reported"] if key == "total_tokens" else evaluators[k][key] for k in ("llm", "jev")]
        if key == "answer_success_rate":
            values = [100 * v for v in values]
            ax.set_ylim(0, 112)
        ax.bar(labels, values, color=colors, width=.55)
        for i, v in enumerate(values):
            ax.annotate(f"{v:.1f}", (i, v), xytext=(0, 4), textcoords="offset points", ha="center")
        ax.set_title(title)
    fig.suptitle("Matched trajectory evaluation — same cases and questions", weight="bold")
    fig.savefig(output / "judge-comparison.png", dpi=170)
    plt.close(fig)
    if agents:
        names = list(agents)
        fig, axes = plt.subplots(2, 3, figsize=(12, 6.5), layout="constrained")
        specs = [("task_completion_rate", "Task completion (%)", 100),
                 ("tool_parameter_accuracy", "Valid tool parameters (%)", 100),
                 ("fact_coverage", "Required fact coverage (%)", 100),
                 ("mean_model_calls", "Mean Agent model calls", 1),
                 ("total_tokens", "Mean reported tokens", 1),
                 ("p95_latency_seconds", "P95 task latency (s)", 1)]
        for ax, (key, title, factor) in zip(axes.flat, specs):
            values = [agents[n][key]["mean_reported"] if key == "total_tokens" else agents[n][key] for n in names]
            values = [factor * v if v is not None else 0 for v in values]
            ax.bar(names, values, color=["#97a1b9", "#8d7be8", "#48ae9a"][:len(names)])
            ax.set_title(title)
            ax.tick_params(axis="x", labelsize=9)
        fig.suptitle("Frozen held-out Agent policy comparison", weight="bold")
        fig.savefig(output / "agent-policies.png", dpi=170)
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--judge-dir", type=Path)
    parser.add_argument("--agent-root", type=Path)
    args = parser.parse_args()
    root = args.run_root
    judge = json.loads(((args.judge_dir or root / "judge-comparison") / "summary.json").read_text())
    source = args.agent_root or root
    agents = {name: summarize_traces(source / ("holdout-" + name)) for name in ("fixed", "adaptive", "budgeted")
              if (source / ("holdout-" + name)).exists()}
    report = {"judges": judge, "agents": agents}
    (root / "combined-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    charts(judge, agents, root / "figures")
    print(json.dumps({"output": str(root / "combined-summary.json"), "agent_policies": list(agents)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
