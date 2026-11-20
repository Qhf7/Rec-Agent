"""Publish per-reason risk, appeal and disposition comparisons against Jev."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from agent_benchmark.provider_report import LABELS

ORDER = ("deepseek_max", "jev", "chatgpt61_sol_xhigh", "kimi_k31_thinking", "claude_opus55", "qwen38_max")
NAMES = {"deepseek_max": "DeepSeek V4.1 Flash", "jev": "Jev 1.14.0", "chatgpt61_sol_xhigh": "ChatGPT 6.1 Sol",
         "kimi_k31_thinking": "Kimi K3.1 Pro", "claude_opus55": "Claude Opus 5.5", "qwen38_max": "Qwen3.8-Max"}
RISK_ZH = {"compliant": "合规", "absolute_claim": "绝对化", "efficacy_or_medical_claim": "功效医疗",
           "price_misleading": "价格误导", "missing_ai_disclosure": "披露缺失", "off_topic": "偏题"}


def generate(run: Path, output: Path) -> dict:
    run, output = Path(run), Path(output)
    manifest = json.loads((run / "manifest.json").read_text())
    summary = json.loads((run / "summary.json").read_text())
    rows = json.loads((run / "results.json").read_text())
    output.mkdir(parents=True, exist_ok=True)
    cases = {c["case_id"]: c for c in manifest["cases"]}
    flat = []
    for r in rows:
        bundle = cases[r["case_id"]]["bundle"]
        d = r.get("decision") or {}
        flat.append({"case_id": r["case_id"], "model": NAMES.get(r["kind"], r["kind"]), "evaluator": r["kind"],
                     "reason": bundle["exposure_reason"], "item_id": bundle["item_id"],
                     "disclosure": bundle.get("disclosure"),
                     "disclosure_status": (bundle.get("disclosure") or {}).get("status"),
                     "status": r["status"], "failure_type": r.get("failure_type"),
                     "risk_type": d.get("risk_type"), "attractiveness_score": d.get("attractiveness_score"),
                     "decision": d.get("decision"), "usage": r["usage"], "latency_seconds": r["latency_seconds"],
                     "input_sha256": r["input_sha256"]})
    (output / "results.json").write_text(json.dumps(flat, ensure_ascii=False, indent=2))
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = [k for k in flat[0] if k not in ("usage", "disclosure")]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(flat)
    by = {(r["case_id"], r["evaluator"]): r for r in flat}
    names = [n for n in ORDER if n in summary["evaluators"]]
    md = ["# 商品理由逐条判断", "", "同一理由与事实，风险六选一及吸引力两题；Jev是对照，不是人工金标。", "",
          "| 案例 / 曝光理由 / 披露状态 | " + " | ".join(LABELS[n] for n in names) + " |",
          "| --- | " + " | ".join("---" for _ in names) + " |"]
    for case_id, case in cases.items():
        reason = case["bundle"]["exposure_reason"].replace("|", "\\|")
        values = []
        for name in names:
            r = by[(case_id, name)]
            if r["status"] != "ok":
                values.append("格式或接口错误")
            else:
                values.append(f"{RISK_ZH[r['risk_type']]} / {r['attractiveness_score']:.2f} / {'曝光' if r['decision']=='expose' else '改写'}")
        disclosure = (case["bundle"].get("disclosure") or {}).get("status", "unknown")
        md.append("| " + case_id + " · " + reason + " · " + disclosure + " | " + " | ".join(values) + " |")
    (output / "case-table.md").write_text("\n".join(md) + "\n")
    _figures(cases, names, by, summary, output)
    return {"cases": len(cases), "requests": len(rows), "output": str(output)}


def _figures(cases, names, by, summary, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    case_ids = list(cases)
    values = np.array([[by[(c, n)]["attractiveness_score"] if by[(c, n)]["status"] == "ok" else np.nan
                        for n in names] for c in case_ids])
    figure, ax = plt.subplots(figsize=(11, 8), layout="constrained")
    palette = plt.get_cmap("YlGnBu").copy()
    palette.set_bad("#e4e7ed")
    im = ax.imshow(values, cmap=palette, vmin=1, vmax=100, aspect="auto")
    ax.set_xticks(range(len(names)), [LABELS[n].replace(" (", "\n(") for n in names], fontsize=8)
    ax.set_yticks(range(len(case_ids)), case_ids)
    for i, c in enumerate(case_ids):
        for j, n in enumerate(names):
            r = by[(c, n)]
            label = "ERROR" if r["status"] != "ok" else f"{r['attractiveness_score']:.1f}\n{'EXPOSE' if r['decision']=='expose' else 'REWRITE'}"
            ax.text(j, i, label, ha="center", va="center", color="white" if values[i, j] > 55 else "#26334a", fontsize=8)
    figure.colorbar(im, ax=ax, label="Mapped appeal score (1–100)", shrink=.8)
    ax.set_title("Same advertising reasons — appeal scores and final dispositions", weight="bold")
    figure.supxlabel("Scalar grades and Jev probability expectations share anchors but differ in calibration; errors are not rewritten as decisions.", fontsize=8)
    figure.savefig(output / "judgment-heatmap.png", dpi=160)
    plt.close(figure)
    comparison = summary["jev_comparison"]["comparisons"]
    other = [n for n in names if n != "jev"]
    x = np.arange(len(other))
    figure, ax = plt.subplots(figsize=(11, 4.5), layout="constrained")
    risk = [comparison[n]["risk_agreement_valid"] * 100 if comparison[n]["risk_agreement_valid"] is not None else 0 for n in other]
    decisions = [comparison[n]["decision_agreement_valid"] * 100 if comparison[n]["decision_agreement_valid"] is not None else 0 for n in other]
    a = ax.bar(x - .18, risk, width=.36, color="#7787c5", label="Risk agreement with Jev")
    b = ax.bar(x + .18, decisions, width=.36, color="#48ae9a", label="Disposition agreement with Jev")
    ax.bar_label(a, fmt="%.1f", padding=3, fontsize=8)
    ax.bar_label(b, fmt="%.1f", padding=3, fontsize=8)
    ax.set_xticks(x, [LABELS[n].replace(" (", "\n(") for n in other], fontsize=8, rotation=12)
    ax.set_ylim(0, 115)
    ax.set_ylabel("Agreement on complete pairs (%)")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title("Matched judgments against Jev — agreement is not accuracy", weight="bold")
    figure.supxlabel("Only valid paired answers; incomplete pairs remain listed separately.", fontsize=9)
    figure.savefig(output / "jev-agreement.png", dpi=160)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.run, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
