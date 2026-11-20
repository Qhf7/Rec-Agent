"""Generate measured tables and figures from a frozen provider comparison."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


LABELS = {
    "deepseek_no_thinking": "DeepSeek (thinking disabled)",
    "jev": "Jev 1.14.0",
    "highland_sol_requested_ultra": "Sol (request Ultra; returned xhigh)",
}


def generate(run: Path, output: Path) -> dict:
    run, output = Path(run), Path(output)
    summary = json.loads((run / "summary.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    results = json.loads((run / "results.json").read_text())
    output.mkdir(parents=True, exist_ok=True)
    aggregates = summary["evaluators"]
    order = [name for name in LABELS if name in aggregates]
    order += [name for name in aggregates if name not in order]
    rows = []
    for name in order:
        m = aggregates[name]
        rows.append({"evaluator": name, "requested_model": m["config"]["model"],
                     "requested_reasoning": m["config"]["reasoning_effort"],
                     "returned_reasoning": ",".join(m.get("returned_reasoning_efforts", [])),
                     "requests": m["requests"], "valid_answers": m["valid_answers"],
                     "task_agreement": m["agreement_all_attempts"]["task_completed"],
                     "parameter_agreement": m["agreement_all_attempts"]["tool_parameters"],
                     "coverage_agreement": m["agreement_all_attempts"]["fact_coverage"],
                     "mean_input_tokens": m["prompt_tokens"]["mean_reported"],
                     "mean_output_tokens": m["completion_tokens"]["mean_reported"],
                     "mean_total_tokens": m["total_tokens"]["mean_reported"],
                     "mean_reasoning_tokens": m["reasoning_tokens"]["mean_reported"],
                     "estimated_usage_requests": m.get("estimated_usage_requests", 0),
                     "p95_seconds": m["p95_latency_seconds"],
                     "transport_failures": m["transport_failures"], "parse_failures": m["parse_failures"]})
    with (output / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    safe = {"schema_version": summary["schema_version"], "case_count": summary["case_count"],
            "workers": summary["workers"], "repeats": summary["repeats"],
            "source_manifest_sha256": manifest["source_manifest_sha256"],
            "reference_type": summary["reference_type"], "evaluators": aggregates,
            "measurement_notes": [
                "Same frozen 24 trajectories and questions; only evaluator/provider configuration differs.",
                "All attempted requests remain in agreement and latency denominators.",
                "Token means use reported usage; estimated usage is explicitly flagged.",
                "Requested Ultra and returned effort are separate; no backend identity attestation.",
                "Programmatic structural checks are not independent human semantic quality labels."]}
    (output / "summary.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2))
    flat = []
    for r in results:
        flat.append({"case_id": r["case_id"], "evaluator": r["kind"], "status": r["status"],
                     "reference": r["reference"], "choices": r.get("choices"),
                     "latency_seconds": r["latency_seconds"], "usage": r["usage"],
                     "requested_reasoning_effort": r["metadata"].get("requested_reasoning_effort"),
                     "returned_reasoning_effort": r["metadata"].get("returned_reasoning_effort"),
                     "input_sha256": r["input_sha256"]})
    (output / "case-results.json").write_text(json.dumps(flat, ensure_ascii=False, indent=2))
    _figures(order, aggregates, output)
    return {"output": str(output), "cases": len(manifest["cases"]), "requests": len(results)}


def _figures(order: list[str], metrics: dict, output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})
    labels = [LABELS.get(name, name).replace(" (", "\n(").replace("; returned", ";\nreturned") for name in order]
    colors = ["#8d7be8", "#48ae9a", "#dcaa62"][:len(order)]
    figure, axes = plt.subplots(2, 3, figsize=(13, 7), layout="constrained")
    specs = [("answer_success_rate", "Valid answers (%)"),
             ("task_completed", "Task agreement with executable checks (%)"),
             ("tool_parameters", "Parameter agreement (%)"),
             ("fact_coverage", "Fact-coverage agreement (%)"),
             ("p95_latency_seconds", "P95 judge latency (s)"),
             ("total_tokens", "Mean reported tokens (Sol: estimated)")]
    for ax, (key, title) in zip(axes.flat, specs):
        values = []
        for name in order:
            m = metrics[name]
            value = m["agreement_all_attempts"][key] if key in m["agreement_all_attempts"] else m[key]
            if key == "total_tokens":
                value = value["mean_reported"]
            elif key != "p95_latency_seconds":
                value *= 100
            values.append(value)
        bars = ax.bar(labels, values, color=colors, width=.6)
        if key not in ("p95_latency_seconds", "total_tokens"):
            ax.set_ylim(0, 112)
        else:
            ax.set_ylim(0, max(values) * 1.2)
        for bar, value in zip(bars, values):
            ax.annotate(f"{value:,.1f}", (bar.get_x() + bar.get_width() / 2, value),
                        xytext=(0, 4), textcoords="offset points", ha="center")
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", labelsize=8)
    figure.suptitle("Three evaluators — identical frozen Agent trajectories and questions", fontsize=14, weight="bold")
    figure.savefig(output / "comparison.png", dpi=170)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.run, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
