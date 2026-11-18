#!/usr/bin/env python3
"""Prepare canonical Jev review cases and a blinded human-label template offline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from canonical_data import load_canonical_items, load_canonical_users
from fact_bundle import build_fact_bundle
from jev_protocol import build_jev_input
from scripts.migrate_legacy_candidates import validate_candidate_contract
from scripts.run_recommendation_workflow import SCENARIO_DATE, canonicalize_recommendations


FIXTURE_PATH = ROOT / "tests/fixtures/jev_review_cases.json"
EVALUATION_SCHEMA = "jev-review-evaluation-v1"
PROVISIONAL_SOURCE = "provisional_agent_review"
HUMAN_SOURCE = "human_adjudicated"
Q2_LABELS = {"supported", "partial", "unsupported", "unverifiable"}
DECISION_LABELS = {"expose", "rewrite", "human_review", "block"}
ORIGINAL_SIX_ITEMS = {"i_0063", "i_0037", "i_0006", "i_0111", "i_0145", "i_0020"}
OUTPUT_NAMES = ("candidates.jsonl", "manifest.json", "human_annotation_template.csv")
ANNOTATION_COLUMNS = (
    "case_id", "item_id", "exposure_reason", "facts_json",
    "reviewer1_id", "reviewer1_q2", "reviewer1_decision",
    "reviewer2_id", "reviewer2_q2", "reviewer2_decision",
    "adjudicator_id", "adjudicated_q2", "adjudicated_decision", "label_source",
)


def load_review_cases(path: str | Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    """Read the frozen editorial fixture, without promoting draft labels to gold."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != EVALUATION_SCHEMA:
        raise ValueError("unsupported evaluation schema")
    if document.get("scenario_date") != SCENARIO_DATE:
        raise ValueError("evaluation scenario date must match canonical data")
    if document.get("label_source") != PROVISIONAL_SOURCE:
        raise ValueError("fixture labels must remain provisional_agent_review")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("evaluation cases must be a non-empty list")
    identifiers, groups, items = set(), {}, {}
    canonical_items, canonical_users = load_canonical_items(), load_canonical_users()
    for case in cases:
        identifier = case.get("case_id")
        if not isinstance(identifier, str) or not re.fullmatch(r"jev_eval_\d{3}", identifier):
            raise ValueError("invalid evaluation case_id")
        if identifier in identifiers:
            raise ValueError("duplicate evaluation case_id")
        identifiers.add(identifier)
        if case.get("label_source") != PROVISIONAL_SOURCE:
            raise ValueError("fixture cannot claim human adjudication")
        if case.get("provisional_q2") not in Q2_LABELS or case.get("provisional_decision") not in DECISION_LABELS:
            raise ValueError("invalid provisional label")
        split, group = case.get("split"), case.get("group_id")
        if split not in {"calibration", "holdout"} or not isinstance(group, str) or not group:
            raise ValueError("invalid evaluation split/group")
        item_id, user_id = case.get("item_id"), case.get("user_id")
        if item_id not in canonical_items or user_id not in canonical_users:
            raise ValueError("unknown evaluation user/item")
        if group in groups and groups[group] != split:
            raise ValueError("group leakage between calibration and holdout")
        if item_id in items and items[item_id] != split:
            raise ValueError("item leakage between calibration and holdout")
        groups[group], items[item_id] = split, split
        if split == "holdout" and item_id in ORIGINAL_SIX_ITEMS:
            raise ValueError("holdout must exclude the original six recommendation items")
        if case.get("scenario_date") != SCENARIO_DATE:
            raise ValueError("case scenario date mismatch")
        omissions = case.get("omit_item_fields", [])
        if not isinstance(omissions, list) or any(not isinstance(f, str) or f not in canonical_items[item_id] or f == "item_id" for f in omissions):
            raise ValueError("invalid omitted item fields")
    return deepcopy(cases)


def candidate_from_case(case: dict[str, Any], *, ai_disclosure: str = "unknown") -> dict[str, Any]:
    """Load trusted facts, optionally omit observations, and exclude all labels."""
    if not re.fullmatch(r"jev_eval_\d{3}", str(case.get("case_id", ""))):
        raise ValueError("invalid evaluation case_id")
    row = {
        "reason_id": "r_eval_" + case["case_id"],
        "user_id": case["user_id"],
        "item_id": case["item_id"],
        "exposure_reason": case["exposure_reason"],
        "generated_reason": case["exposure_reason"],
        "evidence_fields": list(case["evidence_fields"]),
        "context_summary": "",
        "agent_version": "review-evaluation-v1",
    }
    candidate = canonicalize_recommendations([row], input_format="harness", ai_disclosure=ai_disclosure)[0]
    omissions = case.get("omit_item_fields", [])
    if omissions:
        if any(field not in candidate["item_attrs_returned"] or field == "item_id" for field in omissions):
            raise ValueError("invalid omitted item fields")
        for field in omissions:
            candidate["item_attrs_returned"].pop(field)
        candidate["attrs_returned_complete"] = False
        candidate["evidence_fields"] = [
            field for field in candidate["evidence_fields"]
            if not (field.startswith("items.") and field.removeprefix("items.") in omissions)
        ]
        for trace in candidate["tool_trace"]:
            if trace.get("source") == "data/raw/items.csv":
                trace["returned_fields"] = [f for f in trace["returned_fields"] if f not in omissions]
    return validate_candidate_contract(candidate)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _blind_facts(candidate: dict[str, Any]) -> dict[str, Any]:
    facts = build_jev_input(build_fact_bundle(candidate, []))["facts"]
    return {key: value for key, value in facts.items() if key not in {"rule_features", "lexicon_hits"}}


def build_evaluation(output_dir: str | Path, *, fixture_path: str | Path = FIXTURE_PATH, ai_disclosure: str = "unknown") -> dict:
    """Freeze cases and create a blinded annotation sheet; never call a model."""
    output_dir, fixture_path = Path(output_dir), Path(fixture_path)
    cases = load_review_cases(fixture_path)
    candidates = [candidate_from_case(case, ai_disclosure=ai_disclosure) for case in cases]
    if output_dir.exists() and any((output_dir / name).exists() for name in OUTPUT_NAMES):
        raise ValueError("evaluation output already exists; choose a new output directory")
    # Validate the exact snapshots before writing any artifacts.
    blind_rows = []
    for case, candidate in zip(cases, candidates):
        # Reviewers see source facts, not rule/model judgments or expected labels.
        facts = _blind_facts(candidate)
        blind_rows.append({
            "case_id": case["case_id"], "item_id": case["item_id"],
            "exposure_reason": case["exposure_reason"],
            "facts_json": json.dumps(facts, ensure_ascii=False, allow_nan=False, sort_keys=True),
        })
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "candidates.jsonl", candidates)
    with (output_dir / "human_annotation_template.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_COLUMNS)
        writer.writeheader()
        writer.writerows(blind_rows)
    manifest = {
        "schema_version": EVALUATION_SCHEMA, "scenario_date": SCENARIO_DATE,
        "label_source": PROVISIONAL_SOURCE, "eligible_for_threshold_selection": False,
        "human_label_status": "not_provided",
        "annotation_warning": "Draft editorial expectations are not human gold; production thresholds cannot be selected from these labels.",
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "case_count": len(cases), "group_count": len({case["group_id"] for case in cases}),
        "split_counts": dict(Counter(case["split"] for case in cases)),
        "category_counts": dict(Counter(case["category"] for case in cases)),
        "ai_disclosure": ai_disclosure, "network_calls": 0,
        "cases": cases,
        "artifacts": {name.removesuffix(".jsonl").removesuffix(".csv"): str(output_dir / name) for name in ("candidates.jsonl", "human_annotation_template.csv")},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_adjudicated_labels(path: str | Path, cases: list[dict], *, ai_disclosure: str = "unknown") -> dict[str, dict[str, str]]:
    """Read completed human annotations and reject identities or texts that drift."""
    known = {case["case_id"]: case for case in cases}
    labels, seen = {}, set()
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(ANNOTATION_COLUMNS) <= set(reader.fieldnames or []):
            raise ValueError("human annotation CSV is missing required columns")
        for row in reader:
            identifier = row["case_id"]
            if identifier not in known or identifier in seen:
                raise ValueError("unknown or duplicate annotated case_id")
            seen.add(identifier)
            case = known[identifier]
            if row["item_id"] != case["item_id"] or row["exposure_reason"] != case["exposure_reason"]:
                raise ValueError("annotated item/reason differs from frozen case")
            try:
                annotated_facts = json.loads(row["facts_json"])
            except (TypeError, ValueError) as error:
                raise ValueError("annotated facts differ from frozen case") from error
            if annotated_facts != _blind_facts(candidate_from_case(case, ai_disclosure=ai_disclosure)):
                raise ValueError("annotated facts differ from frozen case")
            # An untouched template may remain pending; it is not a label.
            annotation_fields = [column for column in ANNOTATION_COLUMNS if column.startswith(("reviewer", "adjudicat")) or column == "label_source"]
            if not any(row[field].strip() for field in annotation_fields):
                continue
            if row["label_source"] != HUMAN_SOURCE:
                raise ValueError("threshold labels must have human_adjudicated source")
            reviewers = [row["reviewer1_id"].strip(), row["reviewer2_id"].strip()]
            if not all(reviewers) or reviewers[0] == reviewers[1] or not row["adjudicator_id"].strip():
                raise ValueError("two independent reviewers and an adjudicator are required")
            for prefix in ("reviewer1", "reviewer2", "adjudicated"):
                if row[prefix + "_q2"] not in Q2_LABELS or row[prefix + "_decision"] not in DECISION_LABELS:
                    raise ValueError("human labels are incomplete or invalid")
            labels[identifier] = {
                "q2": row["adjudicated_q2"], "decision": row["adjudicated_decision"],
                "label_source": HUMAN_SOURCE, "split": case["split"],
            }
    return labels


def require_calibration_labels(path: str | Path, cases: list[dict], *, ai_disclosure: str = "unknown") -> dict[str, dict[str, str]]:
    """Allow threshold selection only on a completely adjudicated calibration split."""
    labels = load_adjudicated_labels(path, cases, ai_disclosure=ai_disclosure)
    required = {case["case_id"] for case in cases if case["split"] == "calibration"}
    if not required or not required <= labels.keys():
        raise ValueError("complete human_adjudicated calibration labels are required; provisional labels cannot select thresholds")
    return {identifier: labels[identifier] for identifier in sorted(required)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fixture", default=str(FIXTURE_PATH))
    parser.add_argument("--ai-disclosure", choices=("unknown", "visible", "missing"), default="unknown")
    args = parser.parse_args()
    manifest = build_evaluation(args.output_dir, fixture_path=args.fixture, ai_disclosure=args.ai_disclosure)
    print(json.dumps({key: value for key, value in manifest.items() if key != "cases"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
