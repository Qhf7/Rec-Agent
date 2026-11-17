"""Generate natural recommendation candidates through ModelGo DeepSeek fallback Agent."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from modelgo_agent import ModelGoAgent


def load_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def contexts_from_candidates(candidates: list[dict]) -> list[dict]:
    contexts = []
    for candidate in candidates:
        contexts.append({
            "user_id": candidate["user_id"],
            "item_id": candidate["item_id"],
            "user_context": candidate.get("user_context", {}),
            "item": candidate.get("item_attrs_returned", {}),
            "promo": candidate.get("promo_computed_in_code", {}),
        })
    return contexts


def merge_agent_cards(base_candidates: list[dict], cards: list[dict], model: str, start_index: int = 1) -> list[dict]:
    by_user = {card["user_id"]: card for card in cards}
    merged = []
    for index, base in enumerate(base_candidates, start=1):
        card = by_user[base["user_id"]]
        row = dict(base)
        row["reason_id"] = f"r_agent_{start_index + index - 1:04d}"
        row["exposure_reason"] = card.get("exposure_reason", card["generated_reason"])
        row["generated_reason"] = row["exposure_reason"]
        row["generation_mode"] = "modelgo_agent_fallback_v1"
        row["agent_model"] = model
        row["agent_evidence_fields"] = card["evidence_fields"]
        merged.append(row)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="reason_candidates_full.jsonl")
    parser.add_argument("--natural-output", default="reason_candidates_agent_natural.jsonl")
    parser.add_argument("--full-output", default="reason_candidates_agent_full.jsonl")
    parser.add_argument("--report", default="agent_generation_report.json")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    source = load_jsonl(args.source)
    natural = [row for row in source if row.get("source") == "natural"]
    stress = [row for row in source if row.get("source") == "stress"]
    if args.limit:
        natural = natural[: args.limit]
    agent = ModelGoAgent(dry_run=not args.send, timeout=90)
    generated = []
    errors = []
    request_count = 0
    for start in range(0, len(natural), args.batch_size):
        batch = natural[start : start + args.batch_size]
        request_count += 1
        try:
            response = agent.generate_batch(contexts_from_candidates(batch))
            if isinstance(response, dict) and response.get("dry_run"):
                generated.append({"dry_run": True, "request": response["request"], "batch_start": start})
            else:
                generated.extend(merge_agent_cards(batch, response, agent.model, start_index=len(generated) + 1))
        except Exception as exc:
            errors.append({"batch_start": start, "batch_size": len(batch), "error_type": type(exc).__name__, "error": str(exc)[:1000]})
            if args.send:
                # Keep the pipeline moving with a deterministic fallback; report it explicitly.
                for row in batch:
                    fallback = dict(row)
                    fallback["generation_mode"] = "template_fallback_after_agent_error"
                    fallback["agent_model"] = agent.model
                    generated.append(fallback)

    report = {
        "source_natural_count": len(natural),
        "source_stress_count": len(stress),
        "generated_natural_count": len(generated) if args.send else 0,
        "request_count": request_count,
        "error_count": len(errors),
        "errors": errors,
        "model": agent.model,
        "mode": "send" if args.send else "dry_run",
        "note": "ModelGo fallback; official DeepSeek Harness remains blocked until DEEPSEEK_API_KEY is configured.",
    }

    if args.send:
        with Path(args.natural_output).open("w", encoding="utf-8") as handle:
            for row in generated:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        # Reuse the original 100 stress mutations, but give the combined dataset
        # unique IDs and retain their stress labels/source metadata.
        combined = list(generated)
        for offset, row in enumerate(stress, start=1):
            stress_row = dict(row)
            stress_row["reason_id"] = f"r_agent_{len(generated) + offset:04d}"
            combined.append(stress_row)
        with Path(args.full_output).open("w", encoding="utf-8") as handle:
            for row in combined:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        report["combined_count"] = len(combined)
    else:
        with Path(args.natural_output).open("w", encoding="utf-8") as handle:
            for row in generated:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
