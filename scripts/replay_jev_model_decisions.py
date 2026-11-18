#!/usr/bin/env python3
"""Replay frozen Jev responses and preserve the model's Q7 disposition."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from jev_adapter import DEFAULT_MODEL, JevAdapter
from scripts.run_jev_review_comparison import IDENTITY_KEYS, summarize_results

OUTPUT_NAMES = ("decisions.jsonl", "errors.jsonl", "summary.json", "comparison_results.csv")
CSV_COLUMNS = (
    *IDENTITY_KEYS, "item_id", "exposure_reason", "q2", "q2_confidence", "q3", "q4", "q5", "q6",
    "native_q7", "decision", "decision_confidence", "minimum_question_confidence", "risk_type",
    "judge_score", "decision_source", "configuration_notes",
)


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_object)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_request(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != {"model", "state", "questions"}:
        raise ValueError("frozen request must contain model, state and questions")
    state = _read_json(value["state"]) if isinstance(value["state"], str) else value["state"]
    if not isinstance(state, dict) or not isinstance(value["questions"], dict):
        raise ValueError("frozen request state and questions must be objects")
    return dict(value, state=state)


def _matches_identity(record: dict, task: dict) -> bool:
    return all(type(record.get(key)) is type(task[key]) and record.get(key) == task[key] for key in IDENTITY_KEYS)


def load_frozen_comparison(directory: str | Path) -> tuple[dict, list[dict]]:
    """Bind raw bodies to frozen requests, candidate identity and complete facts."""
    directory = Path(directory).resolve()
    manifest = _read_json((directory / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("tasks"), list) or not manifest["tasks"]:
        raise ValueError("comparison manifest requires non-empty tasks")
    model = manifest.get("model", DEFAULT_MODEL)
    if not isinstance(model, str) or not model:
        raise ValueError("comparison model is required")
    indexed, expected_requests = {}, {}
    for task in manifest["tasks"]:
        if not isinstance(task, dict) or any(key not in task for key in IDENTITY_KEYS):
            raise ValueError("frozen task requires complete identity metadata")
        if any(not isinstance(task[key], str) or not task[key] for key in IDENTITY_KEYS if key != "repeat"):
            raise ValueError("frozen task identity fields must be non-empty strings")
        if type(task["repeat"]) is not int or task["repeat"] < 1:
            raise ValueError("comparison repeat must be a positive integer")
        if task["run_id"] in indexed:
            raise ValueError("comparison run_id must be unique")
        bundle = task.get("fact_bundle")
        if not isinstance(bundle, dict) or bundle.get("reason_id") != task["reason_id"]:
            raise ValueError("frozen task reason_id differs from fact bundle")
        adapter = JevAdapter(api_key="", model=model, question_version=task["question_version"], dry_run=True)
        payload = adapter.build_payload(bundle)
        expected_requests[task["run_id"]] = _normalized_request(payload)
        facts = expected_requests[task["run_id"]]["state"]["facts"]
        if task.get("facts_sha256") != hashlib.sha256(_json(facts).encode("utf-8")).hexdigest():
            raise ValueError("comparison facts SHA256 mismatch")
        indexed[task["run_id"]] = dict(task)
    request_path = directory / "requests.jsonl"
    if not request_path.is_file():
        raise ValueError("frozen requests.jsonl is required")
    requests = {}
    for line in request_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = _read_json(line)
        if not isinstance(record, dict):
            raise ValueError("frozen request record must be an object")
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or run_id not in indexed or run_id in requests:
            raise ValueError("unknown or duplicate request run_id")
        if not _matches_identity(record, indexed[run_id]):
            raise ValueError("request metadata differs from frozen task")
        normalized = _normalized_request(record.get("request"))
        if _json(normalized) != _json(expected_requests[run_id]):
            raise ValueError("frozen request payload differs from task candidate, facts, trace or questions")
        requests[run_id] = record
    if set(requests) != set(indexed):
        raise ValueError("missing frozen request run_id")
    response_path = directory / "responses.jsonl"
    responses = {}
    if response_path.exists():
        for line in response_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            response = _read_json(line)
            if not isinstance(response, dict):
                raise ValueError("frozen response record must be an object")
            run_id = response.get("run_id")
            if not isinstance(run_id, str) or run_id not in indexed or run_id in responses:
                raise ValueError("unknown or duplicate response run_id")
            if not _matches_identity(response, indexed[run_id]):
                raise ValueError("response metadata differs from frozen task")
            if not isinstance(response.get("response_body"), str):
                raise ValueError("frozen response_body must be an exact raw string")
            responses[run_id] = response
    return manifest, [dict(task, response_record=responses.get(run_id)) for run_id, task in indexed.items()]


def replay_model_decisions(comparison_dir: str | Path, output_dir: str | Path) -> dict:
    """Parse saved responses without network access; output decision equals Q7."""
    comparison_dir, output_dir = Path(comparison_dir).resolve(), Path(output_dir).resolve()
    if output_dir.exists() and any((output_dir / name).exists() for name in OUTPUT_NAMES):
        raise ValueError("replay output already exists; choose a new output directory")
    manifest, tasks = load_frozen_comparison(comparison_dir)
    model = manifest.get("model", DEFAULT_MODEL)
    decisions, errors, responses = [], [], []
    for task in tasks:
        identity = {key: task[key] for key in IDENTITY_KEYS}
        response = task["response_record"]
        if response is not None:
            responses.append(response)
        try:
            if response is None:
                raise ValueError("frozen response unavailable")
            result = JevAdapter(api_key="", model=model, dry_run=True,
                                question_version=task["question_version"]).parse_response(
                response["response_body"], task["fact_bundle"], expected_protocol=task["question_version"])
            q7 = result.get("question_choices", {}).get("q7_final_decision")
            if result.get("reason_id") != task["reason_id"] or result.get("decision") != q7:
                raise ValueError("parsed disposition must preserve Jev Q7 and candidate identity")
            decisions.append(dict(identity, decision=result))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            errors.append(dict(identity, stage="response_parse", error_type=type(error).__name__, message=str(error)))
    summary = summarize_results(tasks, decisions, responses, errors, live=False, attempts=0, wall_seconds=0)
    summary.update(
        schema_version="jev-model-decision-replay-v1", mode="replay",
        status="completed_with_errors" if errors else "completed",
        source_dir=str(comparison_dir), model=model, source_task_count=len(tasks),
        source_model_response_count=len(responses), decision_source="jev_model",
        decision_question="q7_final_decision", network_calls=0,
        disposition_semantics={"human_review": "Jev disposition label"},
        source_manifest_sha256=_sha256(comparison_dir / "manifest.json"),
        source_requests_sha256=_sha256(comparison_dir / "requests.jsonl"),
        source_responses_sha256=_sha256(comparison_dir / "responses.jsonl") if (comparison_dir / "responses.jsonl").exists() else None,
    )
    for key in ("planned_calls", "attempt_count", "http_response_count", "wall_seconds"):
        summary.pop(key, None)
    for key, group in summary["groups"].items():
        group.pop("attempted", None)
        group["source_task_count"] = sum(task["group"] + "/" + task["question_version"] == key for task in tasks)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("decisions.jsonl", decisions), ("errors.jsonl", errors)):
        (output_dir / name).write_text("".join(_json(row) + "\n" for row in rows), encoding="utf-8")
    by_id = {task["run_id"]: task for task in tasks}
    with (output_dir / "comparison_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in decisions:
            task, result = by_id[row["run_id"]], row["decision"]
            choices, confidences = result["question_choices"], result["question_confidences"]
            writer.writerow({
                **{key: row[key] for key in IDENTITY_KEYS},
                "item_id": task["fact_bundle"]["item_id"], "exposure_reason": task["fact_bundle"]["exposure_reason"],
                "q2": choices["q2_fact_support"], "q2_confidence": confidences["q2_fact_support"],
                "q3": choices["q3_expression_risk"], "q4": choices["q4_commercial_accuracy"],
                "q5": choices["q5_context_relevance"], "q6": choices["q6_safety_gate"],
                "native_q7": choices["q7_final_decision"], "decision": result["decision"],
                "decision_confidence": confidences["q7_final_decision"],
                "minimum_question_confidence": min(confidences.values()), "risk_type": result["risk_type"],
                "judge_score": result["judge_score"], "decision_source": "jev_model",
                "configuration_notes": ";".join(result.get("configuration_notes", [])),
            })
    summary["artifacts"] = {name.split(".")[0]: str(output_dir / name) for name in OUTPUT_NAMES}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        report = replay_model_decisions(args.comparison_dir, args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"replay failed: {error}") from error
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
