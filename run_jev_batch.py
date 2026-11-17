"""Run Jev against fact_bundle.jsonl with explicit dry-run/send modes."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from fact_bundle import load_candidates
from jev_adapter import JevAdapter
from run_rule_baseline import evaluate_report, load_lexicon


def load_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_batch(
    bundles: list[dict], adapter, *, limit: int | None = None
) -> tuple[list[dict], list[dict], dict[str, float]]:
    selected = bundles[:limit] if limit else bundles
    results: list[dict] = []
    errors: list[dict] = []
    timings: dict[str, float] = {}
    for bundle in selected:
        reason_id = bundle.get("reason_id")
        started = time.perf_counter()
        try:
            result = adapter.judge(bundle)
            if not result.get("dry_run"):
                results.append(result)
        except Exception as exc:  # isolate one API failure from the remaining batch
            errors.append(
                {
                    "reason_id": reason_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
            )
        finally:
            timings[reason_id] = round((time.perf_counter() - started) * 1000, 3)
    return results, errors, timings


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = max(0, min(len(values) - 1, int(round(0.95 * (len(values) - 1)))))
    return round(values[index], 3)


def build_report(results: list[dict], errors: list[dict], timings: dict[str, float], labels_path: str | None) -> dict:
    report = {
        "sample_count": len(results) + len(errors),
        "success_count": len(results),
        "error_count": len(errors),
        "average_latency_ms": round(statistics.mean(timings.values()), 3) if timings else 0.0,
        "p95_latency_ms": _p95(list(timings.values())),
        "decision_counts": {},
        "risk_type_counts": {},
        "errors": errors,
        "model_version": results[0]["model_version"] if results else "jev-1.14.0",
        "score_name": results[0]["score_name"] if results else "jev-compliance-v1",
    }
    if results:
        report["decision_counts"] = dict(
            __import__("collections").Counter(row["decision"] for row in results)
        )
        report["risk_type_counts"] = dict(
            __import__("collections").Counter(row["risk_type"] for row in results)
        )
    if labels_path and results:
        labels = list(csv.DictReader(Path(labels_path).open(encoding="utf-8-sig", newline="")))
        report["evaluation"] = evaluate_report(
            results,
            labels,
            model_version=report["model_version"],
            score_name=report["score_name"],
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundles", default="fact_bundle.jsonl")
    parser.add_argument("--labels", default="dev_labels.csv")
    parser.add_argument("--output", default="result_jev.jsonl")
    parser.add_argument("--errors", default="jev_errors.jsonl")
    parser.add_argument("--report", default="jev_batch_report.json")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--send", action="store_true", help="send to the live Jev endpoint")
    args = parser.parse_args()

    bundles = load_jsonl(args.bundles)
    adapter = JevAdapter(dry_run=not args.send, timeout=60)
    results, errors, timings = run_batch(bundles, adapter, limit=args.limit)

    if args.send:
        with Path(args.output).open("w", encoding="utf-8") as handle:
            for result in results:
                handle.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    else:
        # Dry-run writes request previews separately from business decisions.
        with Path(args.output).open("w", encoding="utf-8") as handle:
            for bundle in bundles[: args.limit] if args.limit else bundles:
                preview = adapter.judge(bundle)
                handle.write(json.dumps(preview, ensure_ascii=False, separators=(",", ":")) + "\n")

    with Path(args.errors).open("w", encoding="utf-8") as handle:
        for error in errors:
            handle.write(json.dumps(error, ensure_ascii=False, separators=(",", ":")) + "\n")

    report = build_report(results, errors, timings, args.labels if args.send else None)
    with Path(args.report).open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
