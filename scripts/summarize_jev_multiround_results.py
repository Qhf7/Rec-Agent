#!/usr/bin/env python3
"""Verify recorded multiround Jev runs and export chart-ready observations.

Reads local workflow artifacts only; never calls a model. The input directory
contains inputs/H1.json ... H3.json, fresh/H1-r1 ... H3-r3, controls-live,
controls-replay and unknown-user. No accuracy or CTR estimate is produced.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from canonical_data import load_canonical_items, load_canonical_users
from jev_adapter import JevAdapter
from jev_two_question import RISK_TYPES, TWO_QUESTION_SCHEMA_VERSION
from scripts.strict_json_output import strict_json_loads

QUESTIONS = {"risk_type", "attractiveness_score"}
HISTORY_KEYS = {
    "user_id", "recent_cart_item_ids", "recent_order_item_ids", "last_search_terms",
    "preferred_categories", "price_sensitivity", "aov_90d", "orders_90d",
    "recommendation_history", "history", "history_available", "history_status",
    "category_stats", "events", "event_count", "clicked_count", "ctr", "smoothed_ctr",
    "recent_clicked_item_ids", "recent_shown_item_ids", "recent_ignored_item_ids",
    "sales_30d", "rating", "return_rate_30d", "complaint_rate_30d", "context_summary",
}


def read(path: Path):
    return strict_json_loads(path.read_text(encoding="utf-8-sig"))


def rows(path: Path) -> list[dict]:
    return [strict_json_loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(keys(v) for v in value.values()), set())
    if isinstance(value, list):
        return set().union(*(keys(v) for v in value), set())
    return set()


def payload_object(payload: dict) -> dict:
    return dict(payload, state=strict_json_loads(payload["state"]))


def verify_call(adapter: JevAdapter, request: dict, raw: str, bundle: dict, saved: dict) -> dict:
    state = strict_json_loads(request["state"])
    require(set(request["questions"]) == QUESTIONS == set(state["questions"]), "request must have exactly two questions")
    require(request["questions"] == state["questions"], "inner and outer questions differ")
    require(set(request["questions"]["risk_type"]["criteria"]) == RISK_TYPES, "risk choices differ")
    require(len(request["questions"]["attractiveness_score"]["criteria"]) == 10, "score requires ten grades")
    require(not (keys(state) & HISTORY_KEYS), "private behavioral or excluded fields reached Jev")
    require(payload_object(request) == payload_object(adapter.build_payload(bundle)), "saved request differs from frozen facts")
    response = strict_json_loads(raw)
    parsed = adapter.parse_response(response, bundle, expected_protocol=TWO_QUESTION_SCHEMA_VERSION)
    require(parsed == saved, "reparsed response differs from saved decision")
    answer = response["answers"]["attractiveness_score"]
    probabilities = answer.get("probabilities")
    if probabilities:
        total = sum(Decimal(str(v)) for v in probabilities.values())
        expected = sum(Decimal(k) * Decimal(str(v)) for k, v in probabilities.items()) / total
    else:
        expected = Decimal(str(answer["score"]))
    score = float(Decimal(1) + Decimal(11) * expected)
    require(abs(score - saved["attractiveness_score"]) < 1e-9, "score mapping differs")
    compliance = "Y" if saved["risk_type"] == "compliant" else "N"
    decision = "expose" if compliance == "Y" and saved["attractiveness_score"] > 50 else "rewrite"
    require(saved["compliance"] == compliance and saved["decision"] == decision, "disposition formula differs")
    return response.get("usage", {})


def describe(records: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in records:
        groups[(row["round_id"], row["case_id"])].append(row)
    ranges = [max(r["attractiveness_score"] for r in group) - min(r["attractiveness_score"] for r in group) for group in groups.values()]
    return {
        "calls": len(records), "case_ids": len(groups),
        "decision_counts": dict(Counter(r["decision"] for r in records)),
        "risk_counts": dict(Counter(r["risk_type"] for r in records)),
        "compliance_counts": dict(Counter(r["compliance"] for r in records)),
        "mean_score": mean(r["attractiveness_score"] for r in records),
        "score_min": min(r["attractiveness_score"] for r in records),
        "score_max": max(r["attractiveness_score"] for r in records),
        "risk_unanimous_cases": sum(len({r["risk_type"] for r in g}) == 1 for g in groups.values()),
        "decision_unanimous_cases": sum(len({r["decision"] for r in g}) == 1 for g in groups.values()),
        "threshold_crossing_cases": sum(min(r["attractiveness_score"] for r in g) <= 50 < max(r["attractiveness_score"] for r in g) for g in groups.values()),
        "mean_within_case_score_range": round(mean(ranges), 6), "max_within_case_score_range": round(max(ranges), 6),
    }


def summarize(base: Path) -> dict:
    adapter = JevAdapter(api_key="", dry_run=True, question_version=TWO_QUESTION_SCHEMA_VERSION)
    records, usage, replayed = [], Counter(), 0
    input_checks = []
    canonical_users, canonical_items = load_canonical_users(), load_canonical_items()
    for round_id in ("H1", "H2", "H3"):
        document = read(base / "inputs" / f"{round_id}.json")
        require(len(document["recommendations"]) == 3, "new round requires three candidates")
        require(all(canonical_users[document["user_id"]][k] == v for k, v in document["user_profile"].items()), "profile differs from canonical facts")
        for card in document["recommendations"]:
            require(card["title"] == canonical_items[card["item_id"]]["title"], "title differs from canonical item")
            require(card["exposure_reason"] == card["generated_reason"], "reason aliases differ")
            require(0 < len(card["exposure_reason"]) <= 20, "reason exceeds length limit")
            input_checks.append({"round_id": round_id, "item_id": card["item_id"], "length": len(card["exposure_reason"])})
        frozen_requests = None
        for repeat in range(1, 4):
            directory = base / "fresh" / f"{round_id}-r{repeat}"
            report = read(directory / "workflow_report.json")
            require(report["network_calls"] == report["decision_count"] == report["request_count"] == 3 and report["error_count"] == 0, "incomplete fresh run")
            bundles = {r["reason_id"]: r for r in rows(directory / "fact_bundles.jsonl")}
            requests = {r["reason_id"]: r["request"] for r in rows(directory / "jev_requests.jsonl")}
            responses = {r["reason_id"]: r["response_body"] for r in rows(directory / "jev_responses.jsonl")}
            decisions = {r["reason_id"]: r for r in rows(directory / "jev_decisions.jsonl")}
            require(len(bundles) == len(requests) == len(responses) == len(decisions) == 3, "duplicate or missing records")
            normalized = {k: payload_object(v) for k, v in requests.items()}
            if frozen_requests is None:
                frozen_requests = normalized
            require(frozen_requests == normalized, "repeat input changed")
            combined = read(directory / "workflow_results.json")["recommendations"]
            for card in combined:
                identity = card["reason_id"]
                decision = decisions[identity]
                require(card["jev_audit"] == decision, "joined audit differs")
                usage.update(verify_call(adapter, requests[identity], responses[identity], bundles[identity], decision))
                records.append({"source": "fresh_harness", "round_id": round_id,
                                "case_id": card["item_id"], "repeat": repeat,
                                **{k: card[k] for k in ("user_id", "item_id", "title", "exposure_reason")},
                                **{k: decision[k] for k in ("risk_type", "attractiveness_score", "compliance", "decision", "confidence")},
                                "ai_disclosure": "unknown"})
                replayed += 1
    directory = base / "controls-live"
    manifest = read(directory / "manifest.json")
    tasks = {t["run_id"]: t for t in manifest["tasks"]}
    requests = {r["run_id"]: r["request"] for r in rows(directory / "requests.jsonl")}
    responses = {r["run_id"]: r["response_body"] for r in rows(directory / "responses.jsonl")}
    decisions = {r["run_id"]: r["decision"] for r in rows(directory / "decisions.jsonl")}
    replay = {r["run_id"]: r["decision"] for r in rows(base / "controls-replay" / "decisions.jsonl")}
    require(len(tasks) == len(requests) == len(responses) == len(decisions) == 39 and decisions == replay, "controls incomplete or replay differs")
    for run_id, task in tasks.items():
        bundle, decision = task["fact_bundle"], decisions[run_id]
        usage.update(verify_call(adapter, requests[run_id], responses[run_id], bundle, decision))
        records.append({"source": "frozen_controls", "round_id": "controls", "case_id": task["case_id"],
                        "repeat": task["repeat"], "user_id": "u_0199", "group": task["group"],
                        "item_id": bundle["item_id"], "title": bundle["item"]["title"], "exposure_reason": bundle["exposure_reason"],
                        "ai_disclosure": task["ai_disclosure"],
                        **{k: decision[k] for k in ("risk_type", "attractiveness_score", "compliance", "decision", "confidence")}})
        replayed += 1
    unknown = read(base / "unknown-user" / "workflow_report.json")
    require(all(unknown[k] == 0 for k in ("candidate_count", "request_count", "decision_count", "network_calls", "error_count")), "unknown user must have zero requests")
    summary = {source: describe([r for r in records if r["source"] == source]) for source in ("fresh_harness", "frozen_controls")}
    metadata = {"date": "2026-11-20", "schema_version": "jev-multiround-observations-v1",
                "question_schema_version": TWO_QUESTION_SCHEMA_VERSION, "model": adapter.model,
                "policy_version": "jev-two-policy-v1", "scenario_date": "2026-06-15",
                "live_calls": len(records), "offline_reparsed_equal": replayed,
                "request_contract_and_history_isolation_verified": len(records),
                "score_mapping_and_disposition_verified": len(records),
                "unknown_user_network_calls": 0, "input_checks": input_checks,
                "jev_reported_usage": dict(usage), "summary": summary,
                "label_status": "no_independent_human_gold", "accuracy": None,
                "frozen_control_independent_content_conditions": len({
                    (t["fact_bundle"]["item_id"], t["fact_bundle"]["exposure_reason"], t["ai_disclosure"])
                    for t in tasks.values()
                }),
                "source_note": "Fresh recommendation copy and card fields transcribed from observed desktop final answers without changes; profile fields reconstructed from canonical data matching the displayed export. Frozen controls counted separately."}
    return {"metadata": metadata, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    document = summarize(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(document["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
