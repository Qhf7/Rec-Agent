"""Generate measured tables and figures from a frozen provider comparison."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from dataclasses import fields
from agent_benchmark.costs import Price, compare_cache_policies
from agent_benchmark.providers import usage_of


LABELS = {
    "deepseek_no_thinking": "DeepSeek V4.1 Flash (thinking disabled)",
    "deepseek_max": "DeepSeek V4.1 Flash (Max)",
    "jev": "Jev 1.14.0",
    "highland_sol_requested_ultra": "ChatGPT 6.1 Sol (xhigh)",
    "chatgpt61_sol_xhigh": "ChatGPT 6.1 Sol (xhigh)",
    "kimi_k31_thinking": "Kimi K3.1 Pro (thinking on)",
    "claude_opus55": "Claude Opus 5.5 (provider default)",
    "qwen38_max": "Qwen3.8-Max (thinking on)",
}


def _aggregate_only(value):
    if isinstance(value, dict):
        return {key: _aggregate_only(part) for key, part in value.items() if key != "request_costs"}
    if isinstance(value, list):
        return [_aggregate_only(part) for part in value]
    return value


def generate(run: Path, output: Path, prices_path: Path | None = None) -> dict:
    run, output = Path(run), Path(output)
    summary = json.loads((run / "summary.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    results = json.loads((run / "results.json").read_text())
    # Older runs normalized token totals before cache-write fields were retained.
    # Recover those counters from the immutable saved response, never assume zero.
    for result in results:
        response_path = run / f"{result['case_id']}_{result['kind']}_{result.get('repeat', 1)}" / "response.json"
        if response_path.is_file():
            observed = usage_of(json.loads(response_path.read_text()))
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if result["usage"].get(key) is not None and observed.get(key) != result["usage"][key]:
                    raise ValueError("saved response usage differs from frozen result")
            result["usage"] = observed
    output.mkdir(parents=True, exist_ok=True)
    aggregates = summary["evaluators"]
    order = [name for name in LABELS if name in aggregates]
    order += [name for name in aggregates if name not in order]
    costing = {}
    common_costing = {}
    common_cases = set()
    price_data = json.loads(Path(prices_path).read_text()) if prices_path else None
    if price_data:
        allowed = {f.name for f in fields(Price)}
        measured_sets = [{r["case_id"] for r in results if r["kind"] == name
            and type(r["usage"].get("prompt_tokens")) is int
            and type(r["usage"].get("completion_tokens")) is int} for name in order]
        common_cases = set.intersection(*measured_sets) if measured_sets else set()
        for name in order:
            source = price_data["evaluators"].get(name)
            if source:
                price = Price.from_dict({k: v for k, v in source.items() if k in allowed})
                selected = [r for r in results if r["kind"] == name]
                costing[name] = compare_cache_policies(selected, price)
                paired = [r for r in selected if r["case_id"] in common_cases]
                common_costing[name] = compare_cache_policies(paired, price)
                if "offpeak" in price.variants:
                    costing[name]["offpeak"] = compare_cache_policies(selected, price, variant="offpeak")
                    common_costing[name]["offpeak"] = compare_cache_policies(paired, price, variant="offpeak")
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
        if name in costing:
            cold, observed = costing[name]["cold"], costing[name]["observed"]
            rows[-1].update(official_cold_usd_per_1000=cold["per_1000_measured_usd"],
                            official_observed_low_usd_per_1000=observed["per_1000_measured_lower_usd"],
                            official_observed_high_usd_per_1000=observed["per_1000_measured_upper_usd"],
                            cost_measured_requests=cold["measured_requests"],
                            paired_official_cold_usd_per_1000=common_costing[name]["cold"]["per_1000_measured_usd"],
                            paired_measured_cases=len(common_cases))
    with (output / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    safe = {"schema_version": summary["schema_version"], "case_count": summary["case_count"],
            "workers": summary["workers"], "repeats": summary["repeats"],
            "source_manifest_sha256": manifest["source_manifest_sha256"],
            "reference_type": summary["reference_type"], "evaluators": aggregates,
            "measurement_notes": [
                "Same frozen trajectories and questions; only evaluator/provider configuration differs.",
                "All attempted requests remain in agreement and latency denominators.",
                "Token means use reported usage; estimated usage is explicitly flagged.",
                "Chart labels use reported reasoning settings; raw request metadata remains available for auditing.",
                "Programmatic structural checks are not independent human semantic quality labels."]}
    if price_data:
        safe["official_price_reference"] = price_data
        safe["cost_equivalents"] = _aggregate_only(costing)
        safe["paired_cost_equivalents"] = {"case_ids": sorted(common_cases), "case_count": len(common_cases), "evaluators": _aggregate_only(common_costing)}
        safe["measurement_notes"].append("Costs are official list-price equivalents, not third-party invoices; cold-cache figures normalize all input as cache misses.")
        (output / "costs.json").write_text(json.dumps(_aggregate_only(costing), ensure_ascii=False, indent=2))
        (output / "paired-costs.json").write_text(json.dumps(safe["paired_cost_equivalents"], ensure_ascii=False, indent=2))
    (output / "summary.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2))
    flat = []
    for r in results:
        flat.append({"case_id": r["case_id"], "evaluator": r["kind"], "status": r["status"],
                     "reference": r["reference"], "choices": r.get("choices"),
                     "latency_seconds": r["latency_seconds"], "usage": r["usage"],
                     "requested_reasoning_effort": r["metadata"].get("requested_reasoning_effort"),
                     "returned_reasoning_effort": r["metadata"].get("returned_reasoning_effort"),
                     "input_sha256": r["input_sha256"]})
    if price_data:
        per_case_costs = []
        for name in order:
            selected = [r for r in results if r["kind"] == name]
            for index, result in enumerate(selected):
                record = {"case_id": result["case_id"], "evaluator": name, "paired_case": result["case_id"] in common_cases}
                for policy in ("observed", "cold"):
                    cost = costing[name][policy]["request_costs"][index]
                    record[policy] = {key: cost.get(key) for key in ("cost_usd", "cost_lower_usd", "cost_upper_usd",
                        "usage_estimated", "input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens", "reasons")}
                per_case_costs.append(record)
        (output / "case-costs.json").write_text(json.dumps(per_case_costs, ensure_ascii=False, indent=2))
    (output / "case-results.json").write_text(json.dumps(flat, ensure_ascii=False, indent=2))
    _figures(order, aggregates, output, common_costing or costing)
    return {"output": str(output), "cases": len(manifest["cases"]), "requests": len(results)}


def _figures(order: list[str], metrics: dict, output: Path, costing: dict | None = None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})
    labels = [LABELS.get(name, name).replace(" (", "\n(") for name in order]
    palette = ["#8d7be8", "#48ae9a", "#dcaa62", "#5d9aca", "#ca83a2", "#78945c"]
    colors = [palette[i % len(palette)] for i in range(len(order))]
    figure, axes = plt.subplots(2, 3, figsize=(18 if len(order) > 4 else 15, 9 if len(order) > 4 else 8), layout="constrained")
    specs = [("answer_success_rate", "Valid answers (%)"),
             ("task_completed", "Task agreement with executable checks (%)"),
             ("tool_parameters", "Parameter agreement (%)"),
             ("fact_coverage", "Fact-coverage agreement (%)"),
             ("p95_latency_seconds", "P95 judge latency (s)"),
             (("official_cost", "Paired official-price cost / 1,000 evaluations (USD)") if costing
              else ("total_tokens", "Mean reported tokens"))]
    for ax, (key, title) in zip(axes.flat, specs):
        values = []
        for name in order:
            m = metrics[name]
            if key == "official_cost":
                values.append(costing[name]["cold"]["per_1000_measured_usd"])
                continue
            value = m["agreement_all_attempts"][key] if key in m["agreement_all_attempts"] else m[key]
            if key == "total_tokens":
                value = value["mean_reported"]
            elif key != "p95_latency_seconds":
                value *= 100
            values.append(value)
        bars = ax.bar(labels, values, color=colors, width=.6)
        if key not in ("p95_latency_seconds", "total_tokens", "official_cost"):
            ax.set_ylim(0, 112)
        else:
            ax.set_ylim(0, max(values) * 1.2)
        for bar, value in zip(bars, values):
            label = f"${value:,.3f}" if key == "official_cost" else f"{value:,.1f}"
            ax.annotate(label, (bar.get_x() + bar.get_width() / 2, value),
                        xytext=(0, 4), textcoords="offset points", ha="center")
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", labelsize=7 if len(order) > 4 else 8, rotation=18 if len(order) > 4 else 0)
    figure.suptitle(f"{len(order)} evaluators — identical frozen Agent trajectories and questions", fontsize=14, weight="bold")
    if costing:
        figure.supxlabel("Cost: common measured cases, standard cold-cache list prices; ChatGPT usage estimated; not reseller invoices.", fontsize=9)
    figure.savefig(output / "comparison.png", dpi=170)
    plt.close(figure)
    if costing:
        figure, axes = plt.subplots(1, 2, figsize=(17 if len(order) > 4 else 13, 5.8 if len(order) > 4 else 4.6), layout="constrained")
        for ax, policy, title in zip(axes, ("cold", "observed"),
                                    ("Cold-cache official-price equivalent", "Reported-cache official-price equivalent")):
            for index, name in enumerate(order):
                item = costing[name][policy]
                lower = item["per_1000_measured_lower_usd"]
                upper = item["per_1000_measured_upper_usd"]
                if lower is None or upper is None:
                    continue
                value = item["per_1000_measured_usd"]
                ax.bar(index, value if value is not None else lower, color=colors[index], width=.6)
                if upper > lower:
                    ax.errorbar(index, lower, yerr=[[0], [upper - lower]], color="#314053", capsize=6, fmt="none")
                label = f"${lower:.3f}" if lower == upper else f"${lower:.2f}–{upper:.2f}"
                ax.annotate(label, (index, upper), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=9)
            ax.set_xticks(range(len(order)), labels, fontsize=7 if len(order) > 4 else 8, rotation=18 if len(order) > 4 else 0)
            ax.set_ylabel("USD / 1,000 evaluations")
            ax.set_title(title)
            ax.set_ylim(0, ax.get_ylim()[1] * 1.16)
        figure.suptitle("Cost comparison under two cache assumptions", fontsize=14, weight="bold")
        figure.supxlabel("Common measured cases; DeepSeek peak baseline; ChatGPT usage estimated; ranges retain missing cache details.", fontsize=9)
        figure.savefig(output / "cost-assumptions.png", dpi=170)
        plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prices", type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.run, args.output, args.prices), ensure_ascii=False))


if __name__ == "__main__":
    main()
