"""Generate fact-grounded advertising candidates through ModelGo DeepSeek."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.migrate_legacy_candidates import validate_candidate_contract
from modelgo_agent import AgentResponseError, ModelGoAgent, parse_agent_cards
from recommendation_copy import build_copy_brief


def load_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def contexts_from_candidates(candidates: list[dict]) -> list[dict]:
    contexts = []
    for source in candidates:
        candidate = validate_candidate_contract(source)
        contexts.append({
            "user_id": candidate["user_id"],
            "item_id": candidate["item_id"],
            "user_context": candidate.get("user_context", {}),
            "item": candidate.get("item_attrs_returned", {}),
            "promo": candidate.get("promo_computed_in_code", {}),
            "time_context": {
                "scenario_date": str(candidate["snapshot_at"])[:10],
                "snapshot_at": candidate["snapshot_at"],
                "timezone": "Asia/Shanghai",
            } if candidate.get("snapshot_at") else {},
        })
    return contexts


def merge_agent_cards(base_candidates: list[dict], cards: list[dict], model: str, start_index: int = 1) -> list[dict]:
    contexts = contexts_from_candidates(base_candidates)
    cards = parse_agent_cards({"cards": cards}, [(row["user_id"], row["item_id"]) for row in contexts])
    by_pair = {(card["user_id"], card["item_id"]): card for card in cards}
    merged = []
    for index, (base, context) in enumerate(zip(base_candidates, contexts), start=1):
        card = by_pair[(context["user_id"], context["item_id"])]
        brief = build_copy_brief(context)
        allowed = set(brief["evidence_allowlist"])
        if any(field not in allowed for field in card["evidence_fields"]):
            raise AgentResponseError(f"evidence_fields contains a fact absent from copy_brief: {base['reason_id']}")
        if not any(field.startswith("items.") for field in card["evidence_fields"]):
            raise AgentResponseError(f"evidence_fields requires at least one item fact: {base['reason_id']}")
        row = dict(base)
        row["user_id"], row["item_id"] = context["user_id"], context["item_id"]
        row["source_reason_id"] = base["reason_id"]
        row["reason_id"] = f"r_agent_{start_index + index - 1:04d}"
        row["exposure_reason"] = card["exposure_reason"]
        row["generated_reason"] = row["exposure_reason"]
        row["agent_version"] = "rec-agent-v2"
        row["generation_mode"] = "modelgo_llm_copy_v2"
        row["agent_model"] = model
        row["evidence_fields"] = list(card["evidence_fields"])
        row["agent_evidence_fields"] = list(card["evidence_fields"])
        facts = {**brief["product_facts"], **brief["relevance_hints"], **brief["scene_facts"]}
        row["context_summary"] = "文案依据：" + "；".join(
            f"{field}={json.dumps(facts[field], ensure_ascii=False)}" for field in card["evidence_fields"]
        )
        merged.append(validate_candidate_contract(row))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="reason_candidates.jsonl", help="canonical rec-candidate-v2 JSONL")
    parser.add_argument("--natural-output", default="reason_candidates_agent_natural.jsonl")
    parser.add_argument("--full-output", default="reason_candidates_agent_full.jsonl")
    parser.add_argument("--report", default="agent_generation_report.json")
    parser.add_argument("--request-output", default="agent_generation_requests.jsonl", help="dry-run request preview; candidate outputs are only written with --send")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    outputs = [args.report, args.natural_output, args.full_output] if args.send else [args.report, args.request_output]
    output_paths = [Path(path).resolve() for path in outputs]
    if len(set(output_paths)) != len(output_paths) or Path(args.source).resolve() in output_paths:
        parser.error("source and output paths must all be different")

    source = load_jsonl(args.source)
    natural = [row for row in source if row.get("source") != "stress"]
    stress = [row for row in source if row.get("source") == "stress"]
    if args.limit:
        natural = natural[: args.limit]
    pairs = [(row["user_id"], row["item_id"]) for row in natural]
    if len(set(pairs)) != len(pairs):
        parser.error("natural source contains duplicate user/item pairs; select one source reason per pair")
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

    report = {
        "source_natural_count": len(natural),
        "source_stress_count": len(stress),
        "generated_natural_count": len(generated) if args.send else 0,
        "request_count": request_count,
        "error_count": len(errors),
        "errors": errors,
        "model": agent.model,
        "mode": "send" if args.send else "dry_run",
        "note": "Only validated LLM copy is counted as generated. Jev review runs independently after recommendation generation.",
    }

    for path in output_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    if args.send:
        with Path(args.natural_output).open("w", encoding="utf-8") as handle:
            for row in generated:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        # Retain the source stress set as test mutations, separately identified
        # from copy generated in this run.
        combined = list(generated)
        for offset, row in enumerate(stress, start=1):
            stress_row = dict(row)
            stress_row["source_reason_id"] = row["reason_id"]
            stress_row["reason_id"] = f"r_agent_stress_{offset:04d}"
            stress_row["generation_mode"] = "source_stress_reused"
            combined.append(stress_row)
        with Path(args.full_output).open("w", encoding="utf-8") as handle:
            for row in combined:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        report["combined_count"] = len(combined)
    else:
        with Path(args.request_output).open("w", encoding="utf-8") as handle:
            for row in generated:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
