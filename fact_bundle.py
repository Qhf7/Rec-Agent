"""Build canonical, auditable Jev fact bundles from candidate JSONL records."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from canonical_data import CANONICAL_SCHEMA_VERSION, normalize_item_id
from run_rule_baseline import _price_evidence, _supported_efficacy, _topic_mismatch, find_lexicon_hits


FACT_BUNDLE_SCHEMA = "fact-bundle-v2"


def load_candidates(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _returned_fields(candidate: dict) -> set[str]:
    fields: set[str] = set()
    for trace in candidate.get("tool_trace", []) or []:
        fields.update(str(field) for field in trace.get("returned_fields", []) or [])
    return fields


def _coverage(candidate: dict) -> dict:
    item = candidate.get("item_attrs_returned") or {}
    returned = _returned_fields(candidate)
    expected = {"category_l1", "functions", "suit_audience", "price_cents"}
    missing = sorted(field for field in expected if field not in item and field not in returned)
    complete = bool(candidate.get("attrs_returned_complete", False)) and not missing
    return {
        "returned": sorted(set(item) | returned),
        "missing": missing,
        "complete": complete,
    }


def _provenance(candidate: dict) -> dict:
    user_id = candidate.get("user_id", "unknown")
    item_id = candidate.get("item_id", "unknown")
    promo = candidate.get("promo_computed_in_code") or {}
    promo_id = promo.get("promo_id") or "none"
    item_source = f"data/raw/items.csv:item_id={item_id}"
    user_source = f"data/raw/users.csv:user_id={user_id}"
    return {
        "reason": "canonical-candidate:exposure_reason",
        "user_context": user_source,
        "user_context.city": f"{user_source}:city",
        "item": item_source,
        "item.category_l1": f"{item_source}:category_l1",
        "item.functions": f"{item_source}:functions",
        "item.suit_audience": f"{item_source}:suit_audience",
        "item.price_cents": f"{item_source}:price_cents",
        "promo": f"data/raw/promo_rules.json:promo_id={promo_id}",
        "lexicon_hits": "data/raw/compliance_lexicon.txt:matched_terms",
        "tool_trace": "canonical-candidate:tool_trace",
        "disclosure": "canonical-candidate:ai_disclosure_flag_from_code",
    }


def build_fact_bundle(candidate: dict, lexicon: Iterable[dict]) -> dict:
    if str(candidate.get("item_id", "")).startswith("item_"):
        raise ValueError("legacy candidate item_id must be migrated before Fact Bundle construction")
    exposure_reason = candidate.get("exposure_reason") or candidate.get("generated_reason", "")
    generated_reason = candidate.get("generated_reason") or exposure_reason
    reason = exposure_reason
    item = candidate.get("item_attrs_returned") or {}
    coverage = _coverage(candidate)
    raw_hits = find_lexicon_hits(reason, lexicon)
    lexicon_hits = [
        {
            "term": hit["term"],
            "canonical_term": hit["canonical_term"],
            "risk_type": hit["risk_type"],
            "severity": hit["severity"],
            "match_type": hit["match_type"],
        }
        for hit in raw_hits
    ]
    unsupported_efficacy_terms = [
        hit["canonical_term"]
        for hit in raw_hits
        if hit["risk_type"] == "efficacy_or_medical_claim"
        and not _supported_efficacy(candidate, hit["canonical_term"])
    ]
    supported_efficacy_terms = [
        hit["canonical_term"]
        for hit in raw_hits
        if hit["risk_type"] == "efficacy_or_medical_claim"
        and _supported_efficacy(candidate, hit["canonical_term"])
    ]
    price_mismatch, _ = _price_evidence(
        candidate, [hit for hit in raw_hits if hit["risk_type"] == "price_misleading"]
    )
    topic_mismatch, _ = _topic_mismatch(candidate)
    absolute_claim_terms = [
        hit["canonical_term"] for hit in raw_hits if hit["risk_type"] == "absolute_claim"
    ]

    required_disclosure = candidate.get("ai_disclosure_required", True)
    has_disclosure_flag = "ai_disclosure_flag_from_code" in candidate
    verification_state = "verified"
    if not has_disclosure_flag or not candidate.get("tool_trace") or not coverage["complete"]:
        verification_state = "unverifiable"

    promo = candidate.get("promo_computed_in_code")
    if promo is None:
        promo = {}

    return {
        "schema_version": FACT_BUNDLE_SCHEMA,
        "reason_id": candidate.get("reason_id"),
        "user_id": candidate.get("user_id"),
        "item_id": candidate.get("item_id"),
        "exposure_reason": exposure_reason,
        "generated_reason": generated_reason,
        "evidence_fields": candidate.get("evidence_fields") or [],
        "user_context": candidate.get("user_context") or {},
        "item": item,
        "promo": promo,
        "lexicon_hits": lexicon_hits,
        "disclosure": {
            "flag": candidate.get("ai_disclosure_flag_from_code"),
            "required": required_disclosure,
        },
        "tool_trace": candidate.get("tool_trace") or [],
        "coverage": coverage,
        "verification_state": verification_state,
        "rule_features": {
            "lexicon_hit_count": len(lexicon_hits),
            "attrs_returned_complete": bool(candidate.get("attrs_returned_complete", False)),
            "has_promo": bool(promo),
            "unsupported_efficacy_terms": sorted(set(unsupported_efficacy_terms)),
            "supported_efficacy_terms": sorted(set(supported_efficacy_terms)),
            "absolute_claim_terms": sorted(set(absolute_claim_terms)),
            "price_mismatch": bool(price_mismatch),
            "topic_mismatch": bool(topic_mismatch),
        },
        "provenance": _provenance(candidate),
        "snapshot_at": candidate.get("snapshot_at"),
        "agent_version": candidate.get("agent_version", "rec-agent-v2"),
        "data_version": candidate.get("data_version") or CANONICAL_SCHEMA_VERSION,
    }


def build_fact_bundles(candidates: list[dict], lexicon: list[dict]) -> list[dict]:
    return [build_fact_bundle(candidate, lexicon) for candidate in candidates]


def write_fact_bundles(bundles: list[dict], path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        for bundle in bundles:
            handle.write(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    import argparse
    from run_rule_baseline import load_lexicon

    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default="reason_candidates.jsonl")
    parser.add_argument("--lexicon", default="data/raw/compliance_lexicon.txt")
    parser.add_argument("--output", default="fact_bundle.jsonl")
    args = parser.parse_args()

    candidates = load_candidates(args.candidates)
    lexicon = load_lexicon(args.lexicon)
    bundles = build_fact_bundles(candidates, lexicon)
    write_fact_bundles(bundles, args.output)
    print(f"generated {args.output}: {len(bundles)} bundles")


if __name__ == "__main__":
    main()
