#!/usr/bin/env python3
"""Prepare canonical recommendations and run the separate optional Jev audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from canonical_data import CANONICAL_SCHEMA_VERSION, load_canonical_items, load_canonical_promos, load_canonical_users
from fact_bundle import build_fact_bundle
from generate_full_candidates import promo_snapshot, user_snapshot
from jev_adapter import JevAdapter, JevConfigurationError, validate_decision
from jev_five_question import FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION, FIVE_QUESTION_SCHEMA_VERSION, FIVE_QUESTION_POLICY_VERSION
from jev_protocol import JEV_QUESTION_SCHEMA_VERSION, SUPPORTED_JEV_QUESTION_VERSIONS
from run_rule_baseline import load_lexicon
from scripts.migrate_legacy_candidates import CANDIDATE_SCHEMA_VERSION, validate_candidate_contract


FIVE_QUESTION_PROTOCOLS = {FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION, FIVE_QUESTION_SCHEMA_VERSION}
SCENARIO_DATE = "2026-06-15"
SNAPSHOT_AT = f"{SCENARIO_DATE}T12:00:00+08:00"
AUDIT_FIELDS = {
    "decision", "risk_type", "judge_score", "attractiveness_score", "compliance",
    "escalated", "evidence", "jev_audit",
}
ARTIFACT_NAMES = {
    "candidates": "candidates.jsonl", "fact_bundles": "fact_bundles.jsonl",
    "jev_requests": "jev_requests.jsonl", "decisions": "jev_decisions.jsonl",
    "responses": "jev_responses.jsonl", "errors": "jev_errors.jsonl", "report": "workflow_report.json",
    "workflow_results": "workflow_results.json",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def _strict_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _require_object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def parse_recommendation_input(text: str, *, input_format: str = "auto") -> tuple[str, list[dict]]:
    """Read one strict Harness export or canonical candidate objects in JSONL."""
    if input_format not in {"auto", "harness", "jsonl"}:
        raise ValueError("input_format must be auto, harness or jsonl")
    if not text.strip():
        raise ValueError("input is empty")
    if input_format in {"auto", "harness"}:
        try:
            document = _strict_json(text)
        except json.JSONDecodeError:
            if input_format == "harness":
                raise
        else:
            if isinstance(document, dict) and "recommendations" in document:
                _check_no_audit(document)
                recommendations = document["recommendations"]
                if not isinstance(recommendations, list):
                    raise ValueError("recommendations must be a list")
                # An unknown user can correctly produce no recommendations.
                # Keep the ID format strict, but require stored facts only for
                # exports that actually contain candidates to audit.
                _validate_user_id(document.get("user_id"), require_known=bool(recommendations))
                rows = []
                for recommendation in recommendations:
                    rec = deepcopy(_require_object(recommendation, "recommendation"))
                    _check_no_audit(rec)
                    if "user_id" in rec and rec["user_id"] != document["user_id"]:
                        raise ValueError("recommendation user_id conflicts with exported user_id")
                    rec["user_id"] = document["user_id"]
                    if "agent_version" not in rec and "agent_version" in document:
                        rec["agent_version"] = document["agent_version"]
                    rows.append(rec)
                return "harness", rows
            if input_format == "harness":
                raise ValueError("Harness export requires user_id and recommendations")
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            try:
                rows.append(_require_object(_strict_json(line), "candidate"))
            except ValueError as exc:
                raise ValueError(f"candidate JSONL line {number}: {exc}") from exc
    return "jsonl", rows


def _check_no_audit(row: dict) -> None:
    if AUDIT_FIELDS.intersection(row):
        raise ValueError("recommendation input must not contain Jev audit fields")


def _validate_user_id(value: Any, *, require_known: bool = True) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"u_\d{4}", value):
        raise ValueError("user_id must be a canonical u_#### string")
    if require_known and value not in load_canonical_users():
        raise ValueError(f"unknown user_id: {value}")
    return value


def _validate_candidate_fields(row: dict) -> dict:
    _check_no_audit(row)
    user_id = _validate_user_id(row.get("user_id"))
    item_id = row.get("item_id")
    if not isinstance(item_id, str) or not re.fullmatch(r"i_\d{4}", item_id):
        raise ValueError("item_id must be a canonical item_id i_####")
    if item_id not in load_canonical_items():
        raise ValueError(f"unknown item_id: {item_id}")
    exposure = row.get("exposure_reason", row.get("generated_reason"))
    generated = row.get("generated_reason", exposure)
    if not isinstance(exposure, str) or not exposure.strip():
        raise ValueError("exposure_reason must be a non-empty string")
    if not isinstance(generated, str) or generated != exposure:
        raise ValueError("generated_reason must equal exposure_reason")
    evidence = row.get("evidence_fields", [])
    if not isinstance(evidence, list) or any(not isinstance(field, str) or not field for field in evidence):
        raise ValueError("evidence_fields must be a list of non-empty strings")
    summary = row.get("context_summary", "")
    if not isinstance(summary, str):
        raise ValueError("context_summary must be a string")
    reason_id = row.get("reason_id")
    if reason_id is None:
        identity = json.dumps([user_id, item_id, exposure], ensure_ascii=False, separators=(",", ":"))
        reason_id = "r_export_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    if not isinstance(reason_id, str) or not re.fullmatch(r"r_[A-Za-z0-9_-]{1,120}", reason_id):
        raise ValueError("reason_id must be an r_ prefixed identifier without spaces")
    for field, expected in (("schema_version", CANDIDATE_SCHEMA_VERSION), ("data_version", CANONICAL_SCHEMA_VERSION)):
        if field in row and row[field] != expected:
            raise ValueError(f"{field} mismatch: {row[field]}")
    agent_version = row.get("agent_version", "rec-agent-v2")
    if not isinstance(agent_version, str) or not agent_version.strip():
        raise ValueError("agent_version must be a non-empty string")
    return {
        "reason_id": reason_id, "user_id": user_id, "item_id": item_id,
        "exposure_reason": exposure, "generated_reason": generated,
        "evidence_fields": list(evidence), "context_summary": summary,
        "agent_version": agent_version,
    }


def canonicalize_recommendations(rows: list[dict], *, input_format: str, ai_disclosure: str = "unknown") -> list[dict]:
    """Verify candidate boundaries, then load trusted facts for each recommendation."""
    if ai_disclosure not in {"visible", "missing", "unknown"}:
        raise ValueError("ai_disclosure must be visible, missing or unknown")
    rules = {row["rule_id"]: row for row in load_canonical_promos()}
    candidates = []
    reason_ids: set[str] = set()
    for row in rows:
        candidate = _validate_candidate_fields(row)
        normalized = None
        if input_format == "jsonl":
            # Validate every supplied canonical fact before replacing snapshots.
            normalized = validate_candidate_contract(dict(row, reason_id=candidate["reason_id"]))
        if candidate["reason_id"] in reason_ids:
            raise ValueError(f"duplicate reason_id: {candidate['reason_id']}")
        reason_ids.add(candidate["reason_id"])
        item = deepcopy(load_canonical_items()[candidate["item_id"]])
        user = user_snapshot(load_canonical_users()[candidate["user_id"]])
        promo = promo_snapshot(item, rules, as_of=SCENARIO_DATE)
        complete = True
        if normalized is not None:
            # Replay the verified subset actually present, including omissions.
            supplied_item = normalized["item_attrs_returned"]
            item = {field: deepcopy(item[field]) for field in supplied_item}
            supplied_user = normalized["user_context"]
            user = {field: deepcopy(user[field]) for field in supplied_user if field in user}
            promo = deepcopy(normalized["promo_computed_in_code"])
            complete = normalized["attrs_returned_complete"] is True
        if normalized is None:
            candidate["snapshot_at"] = SNAPSHOT_AT
            candidate["tool_trace"] = [
                {"tool": "local_csv_lookup", "source": "data/raw/users.csv", "returned_fields": sorted(user)},
                {"tool": "local_csv_lookup", "source": "data/raw/items.csv", "returned_fields": sorted(item)},
            ]
            if promo:
                candidate["tool_trace"].append({"tool": "local_csv_lookup", "source": "data/raw/promo_rules.json", "returned_fields": sorted(promo)})
        else:
            # A replay must not manufacture a new observation time or trace.
            for field in ("snapshot_at", "tool_trace"):
                if field in normalized:
                    candidate[field] = deepcopy(normalized[field])
        candidate.update({
            "schema_version": CANDIDATE_SCHEMA_VERSION, "data_version": CANONICAL_SCHEMA_VERSION,
            "user_context": user, "item_attrs_returned": item,
            "attrs_returned_complete": complete, "promo_computed_in_code": promo,
            "ai_disclosure_required": True, "disclosure_status": ai_disclosure,
            "generation_mode": "imported_harness_export" if input_format == "harness" else "imported_canonical_jsonl",
            "source": "standalone_recommendation_workflow",
        })
        if ai_disclosure != "unknown":
            candidate["ai_disclosure_flag_from_code"] = ai_disclosure == "visible"
        candidates.append(validate_candidate_contract(candidate))
    return candidates


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")


def build_workflow_results(candidates: list[dict], decisions: list[dict], errors: list[dict], *, mode: str) -> dict:
    """Join recommendations with Jev results by reason ID for readable export."""
    if mode not in {"prepare", "live", "replay"}:
        raise ValueError("workflow result mode must be prepare, live or replay")
    candidate_ids = [candidate["reason_id"] for candidate in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("workflow results require unique candidate reason_id")
    by_id, errors_by_id = {}, {}
    for decision in decisions:
        validate_decision(decision)
        reason_id = decision["reason_id"]
        if reason_id not in candidate_ids or reason_id in by_id:
            raise ValueError("unknown or duplicate workflow decision reason_id")
        choices = decision.get("question_choices") or {}
        if "q7_final_decision" in choices and decision["decision"] != choices["q7_final_decision"]:
            raise ValueError("workflow decision differs from Jev Q7")
        by_id[reason_id] = deepcopy(decision)
    for error in errors:
        reason_id = error["reason_id"]
        if reason_id not in candidate_ids or reason_id in errors_by_id or reason_id in by_id:
            raise ValueError("unknown, duplicate or conflicting workflow error reason_id")
        errors_by_id[reason_id] = deepcopy(error)
    if mode != "prepare" and len(by_id) + len(errors_by_id) != len(candidates):
        raise ValueError("completed workflow requires a result or error for every recommendation")
    recommendations = []
    for candidate in candidates:
        reason_id = candidate["reason_id"]
        item_id = candidate["item_id"]
        recommendations.append({
            "reason_id": reason_id, "user_id": candidate["user_id"], "item_id": item_id,
            "title": load_canonical_items()[item_id]["title"],
            "exposure_reason": candidate["exposure_reason"],
            "generated_reason": candidate["generated_reason"],
            "evidence_fields": list(candidate.get("evidence_fields") or []),
            "context_summary": candidate.get("context_summary", ""),
            "audit_status": "completed" if reason_id in by_id else "error" if reason_id in errors_by_id else "prepared",
            "jev_audit": by_id.get(reason_id),
        })
    sources = {row.get("decision_source", "jev_model") for row in decisions}
    source = next(iter(sources)) if len(sources) == 1 else "mixed" if sources else "jev_answers_policy"
    return {
        "schema_version": "recommendation-jev-workflow-v1", "mode": mode,
        "decision_source": source, "recommendations": recommendations,
        "errors": deepcopy(errors),
    }


def run_workflow(
    input_path: str | Path, output_dir: str | Path, *, input_format: str = "auto",
    ai_disclosure: str = "unknown", live: bool = False, adapter: Any = None,
    lexicon_path: str | Path | None = None, question_version: str = JEV_QUESTION_SCHEMA_VERSION,
) -> dict:
    """Persist prepare artifacts; only an explicit live run invokes adapter.judge."""
    if question_version not in SUPPORTED_JEV_QUESTION_VERSIONS:
        raise ValueError("unsupported Jev question version")
    if adapter is not None and getattr(adapter, "question_version", question_version) != question_version:
        raise ValueError("adapter question version conflicts with workflow question_version")
    input_path, output_dir = Path(input_path).resolve(), Path(output_dir).resolve()
    actual_format, rows = parse_recommendation_input(input_path.read_text(encoding="utf-8-sig"), input_format=input_format)
    candidates = canonicalize_recommendations(rows, input_format=actual_format, ai_disclosure=ai_disclosure)
    lexicon = load_lexicon(str(lexicon_path or ROOT / "data/raw/compliance_lexicon.txt"))
    bundles = [build_fact_bundle(candidate, lexicon) for candidate in candidates]
    response_path = output_dir / ARTIFACT_NAMES["responses"]
    recorded_responses = []

    def record_response(reason_id: str, response_body: str) -> None:
        record = {"reason_id": reason_id, "response_body": response_body}
        # Write before parsing so a rejected response remains inspectable.
        with response_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        recorded_responses.append(reason_id)

    if adapter is None and bundles:
        adapter = JevAdapter(dry_run=not live, response_observer=record_response if live else None, question_version=question_version)
        if live and not adapter.api_key:
            raise JevConfigurationError("MODELGO_API_KEY is required for --live")
    requests = [{
        "reason_id": bundle["reason_id"], "item_id": bundle["item_id"],
        "dry_run": not live, "request": adapter.build_payload(bundle),
    } for bundle in bundles]
    if output_dir.exists() and any((output_dir / name).exists() for name in ARTIFACT_NAMES.values()):
        raise ValueError("output directory already contains workflow artifacts; choose a new --output-dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {key: str(output_dir / ARTIFACT_NAMES[key]) for key in ("candidates", "fact_bundles", "jev_requests")}
    _write_jsonl(Path(artifacts["candidates"]), candidates)
    _write_jsonl(Path(artifacts["fact_bundles"]), bundles)
    _write_jsonl(Path(artifacts["jev_requests"]), requests)
    decisions, errors = [], []
    calls = 0
    if live:
        for bundle in bundles:
            calls += 1
            try:
                decision = validate_decision(adapter.judge(bundle))
                if decision["reason_id"] != bundle["reason_id"]:
                    raise ValueError("Jev response reason_id does not match request")
                if question_version in FIVE_QUESTION_PROTOCOLS:
                    if decision.get("protocol_completeness") != question_version:
                        raise ValueError("workflow requires a five-question Jev result")
                    required_missing = bundle["disclosure"]["required"] and bundle["disclosure"]["flag"] is False
                    if decision["decision_inputs"]["required_ai_disclosure_missing"] != required_missing:
                        raise ValueError("workflow disclosure does not match the frozen fact bundle")
                choices = decision.get("question_choices") or {}
                if "q7_final_decision" in choices and decision["decision"] != choices["q7_final_decision"]:
                    raise ValueError("workflow decision differs from Jev Q7")
                decisions.append(decision)
            except Exception as exc:
                errors.append({"reason_id": bundle["reason_id"], "error_type": type(exc).__name__, "message": str(exc)})
        artifacts["decisions"] = str(output_dir / ARTIFACT_NAMES["decisions"])
        _write_jsonl(Path(artifacts["decisions"]), decisions)
        if errors:
            artifacts["errors"] = str(output_dir / ARTIFACT_NAMES["errors"])
            _write_jsonl(Path(artifacts["errors"]), errors)
        if recorded_responses:
            artifacts["responses"] = str(response_path)
    artifacts["workflow_results"] = str(output_dir / ARTIFACT_NAMES["workflow_results"])
    combined = build_workflow_results(candidates, decisions, errors, mode="live" if live else "prepare")
    combined["decision_source"] = "jev_answers_policy" if question_version in FIVE_QUESTION_PROTOCOLS else "jev_model"
    combined["question_schema_version"] = question_version
    if question_version in FIVE_QUESTION_PROTOCOLS:
        combined["policy_version"] = FIVE_QUESTION_POLICY_VERSION
    Path(artifacts["workflow_results"]).write_text(
        json.dumps(combined, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8",
    )
    report = {
        "workflow_version": "standalone-recommendation-v3", "mode": "live" if live else "prepare",
        "status": "completed_with_errors" if errors else "prepared" if not live else "completed",
        "input_format": actual_format, "scenario_date": SCENARIO_DATE,
        "data_version": CANONICAL_SCHEMA_VERSION, "ai_disclosure": ai_disclosure,
        "question_schema_version": question_version,
        "decision_source": combined["decision_source"],
        **({"policy_version": FIVE_QUESTION_POLICY_VERSION} if question_version in FIVE_QUESTION_PROTOCOLS else {}),
        "candidate_count": len(candidates), "fact_bundle_count": len(bundles),
        "request_count": len(requests), "decision_count": len(decisions),
        "error_count": len(errors), "network_calls": calls,
        "artifacts": artifacts,
    }
    (output_dir / ARTIFACT_NAMES["report"]).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="strict Harness JSON export or canonical candidate JSONL")
    parser.add_argument("--output-dir", required=True, help="directory for separate workflow artifacts")
    parser.add_argument("--input-format", choices=("auto", "harness", "jsonl"), default="auto")
    parser.add_argument("--ai-disclosure", choices=("visible", "missing", "unknown"), default="unknown", help="actual display disclosure state; default unknown")
    parser.add_argument("--live", action="store_true", help="explicitly call Jev using MODELGO_API_KEY")
    parser.add_argument("--question-version", choices=sorted(SUPPORTED_JEV_QUESTION_VERSIONS), default=JEV_QUESTION_SCHEMA_VERSION)
    args = parser.parse_args()
    try:
        report = run_workflow(args.input, args.output_dir, input_format=args.input_format, ai_disclosure=args.ai_disclosure, live=args.live, question_version=args.question_version)
    except (ValueError, OSError, JevConfigurationError) as exc:
        raise SystemExit(f"workflow failed: {exc}") from exc
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
