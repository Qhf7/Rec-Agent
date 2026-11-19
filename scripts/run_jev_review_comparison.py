#!/usr/bin/env python3
"""Prepare or explicitly run a controlled Q2 comparison; preserve raw responses."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from fact_bundle import build_fact_bundle
from jev_adapter import DEFAULT_MODEL, JevAdapter, JevConfigurationError
from jev_protocol import Q2_LEGACY_QUESTION_SCHEMA_VERSION, V2_JEV_QUESTION_SCHEMA_VERSION
from run_rule_baseline import load_lexicon
from scripts.build_jev_review_evaluation import FIXTURE_PATH, candidate_from_case, load_review_cases
from scripts.run_recommendation_workflow import canonicalize_recommendations, parse_recommendation_input

COMPARISON_SCHEMA = "jev-review-comparison-v2"
VERSIONS = (Q2_LEGACY_QUESTION_SCHEMA_VERSION, V2_JEV_QUESTION_SCHEMA_VERSION)
OUTPUT_NAMES = ("manifest.json", "requests.jsonl", "responses.jsonl", "decisions.jsonl", "errors.jsonl", "summary.json")
IDENTITY_KEYS = ("run_id", "case_id", "group", "question_version", "repeat", "ai_disclosure", "reason_id")


def _identity(task: dict) -> dict:
    return {key: task[key] for key in IDENTITY_KEYS}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(_json(row) + "\n" for row in rows), encoding="utf-8")


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_json(row) + "\n")


def _check_ab_payloads(left: dict, right: dict) -> None:
    """Reject comparisons that change facts or any question other than Q2."""
    if left["model"] != right["model"]:
        raise ValueError("controlled comparison requires the same model")
    aq, bq = deepcopy(left["questions"]), deepcopy(right["questions"])
    if aq.pop("q2_fact_support") == bq.pop("q2_fact_support"):
        raise ValueError("controlled comparison must change Q2")
    if aq != bq:
        raise ValueError("controlled comparison changed a question other than Q2")
    a, b = json.loads(left["state"]), json.loads(right["state"])
    if a["facts"] != b["facts"]:
        raise ValueError("controlled comparison changed facts")
    for state in (a, b):
        state.pop("question_schema_version", None)
        state["questions"].pop("q2_fact_support")
    if a != b:
        raise ValueError("controlled comparison changed candidate, trace, or non-Q2 state")


def _new_task(case_id: str, group: str, version: str, repeat: int, disclosure: str, bundle: dict, metadata: dict) -> dict:
    return {
        "run_id": f"{group}__{case_id}__{version}__{disclosure}__r{repeat}",
        "case_id": case_id, "group": group, "question_version": version,
        "repeat": repeat, "ai_disclosure": disclosure, "reason_id": bundle["reason_id"],
        "fact_bundle": deepcopy(bundle), "facts_sha256": "", "metadata": deepcopy(metadata),
    }


def prepare_tasks(*, fixture_path: str | Path = FIXTURE_PATH, repeats: int = 2,
                  include_original_six: bool = False, original_dir: str | Path | None = None,
                  disclosure_controls: int = 0, model: str = DEFAULT_MODEL) -> tuple[list[dict], list[dict]]:
    """Freeze cases and requests, checking every A/B pair before any network use."""
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if type(disclosure_controls) is not int or disclosure_controls < 0:
        raise ValueError("disclosure_controls must be a non-negative integer")
    cases = load_review_cases(fixture_path)
    lexicon = load_lexicon(str(ROOT / "data/raw/compliance_lexicon.txt"))
    tasks, requests = [], []
    adapters = {v: JevAdapter(model=model, question_version=v, dry_run=True) for v in VERSIONS}

    def add(task: dict, payload: dict | None = None) -> None:
        payload = payload or adapters[task["question_version"]].build_payload(task["fact_bundle"])
        task["facts_sha256"] = _sha256(json.loads(payload["state"])["facts"])
        tasks.append(task)
        requests.append(dict(_identity(task), request=payload))

    for case in cases:
        bundle = build_fact_bundle(candidate_from_case(case, ai_disclosure="unknown"), lexicon)
        pair = {v: adapters[v].build_payload(bundle) for v in VERSIONS}
        _check_ab_payloads(pair[VERSIONS[0]], pair[VERSIONS[1]])
        metadata = {key: case[key] for key in ("split", "category", "group_id")}
        for repeat in range(1, repeats + 1):
            # Alternate order across repeats to limit simple temporal ordering bias.
            order = VERSIONS if repeat % 2 else tuple(reversed(VERSIONS))
            for version in order:
                add(_new_task(case["case_id"], "evaluation", version, repeat, "unknown", bundle, metadata), pair[version])

    if include_original_six:
        source_dir = Path(original_dir or ROOT / "runs/2026-11-18-live-validation")
        count = 0
        for user_id in ("u_0001", "u_0199"):
            source = source_dir / f"{user_id}.json"
            input_format, rows = parse_recommendation_input(source.read_text(encoding="utf-8-sig"), input_format="harness")
            if len(rows) != 3 or any(row["user_id"] != user_id for row in rows):
                raise ValueError("original-six inputs must contain three recommendations for each expected user")
            for candidate in canonicalize_recommendations(rows, input_format=input_format, ai_disclosure="unknown"):
                bundle = build_fact_bundle(candidate, lexicon)
                identifier = f"desktop_{user_id}_{candidate['item_id']}"
                add(_new_task(identifier, "original_six", V2_JEV_QUESTION_SCHEMA_VERSION, 1, "unknown", bundle,
                              {"source": "previous_desktop_final_answer", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}))
                count += 1
        if count != 6:
            raise ValueError("original-six regression requires six candidates")

    controls = []
    seen_items = set()
    for case in cases:
        if case["category"] == "objective" and not case.get("omit_item_fields") and case["item_id"] not in seen_items:
            controls.append(case)
            seen_items.add(case["item_id"])
    if disclosure_controls > len(controls):
        raise ValueError("not enough independent objective cases for requested disclosure controls")
    for case in controls[:disclosure_controls]:
        for disclosure in ("visible", "missing"):
            bundle = build_fact_bundle(candidate_from_case(case, ai_disclosure=disclosure), lexicon)
            add(_new_task(case["case_id"], "disclosure_control", V2_JEV_QUESTION_SCHEMA_VERSION, 1, disclosure, bundle,
                          {"split": case["split"], "category": case["category"], "group_id": case["group_id"],
                           "unknown_control": "same case in evaluation group"}))
    if len({task["run_id"] for task in tasks}) != len(tasks):
        raise ValueError("duplicate comparison run_id")
    return tasks, requests


def summarize_results(tasks: list[dict], decisions: list[dict], responses: list[dict], errors: list[dict],
                      *, live: bool, attempts: int, wall_seconds: float) -> dict:
    """Describe observed answers and repeat stability without calling draft labels gold."""
    answers = {}
    response_parse_errors = 0
    for response in responses:
        try:
            raw = json.loads(response["response_body"])
            if not isinstance(raw, dict) or not isinstance(raw.get("answers"), dict):
                raise ValueError("missing answers")
            answers[response["run_id"]] = raw["answers"]
        except (TypeError, ValueError):
            response_parse_errors += 1
    decision_by_id = {r["run_id"]: r["decision"] for r in decisions}
    groups = defaultdict(lambda: {"attempted": 0, "successful_decisions": 0, "q2_distribution": Counter(), "native_q7_distribution": Counter(), "final_decision_distribution": Counter()})
    paired = defaultdict(dict)
    repeats = defaultdict(list)
    for task in tasks:
        if task["run_id"] not in answers and task["run_id"] not in decision_by_id:
            continue
        key = task["group"] + "/" + task["question_version"]
        group = groups[key]
        a = answers.get(task["run_id"], {})
        q2_answer, q7_answer = a.get("q2_fact_support"), a.get("q7_final_decision")
        q2 = q2_answer.get("choice") if isinstance(q2_answer, Mapping) else None
        q7 = q7_answer.get("choice") if isinstance(q7_answer, Mapping) else None
        q2 = q2 if isinstance(q2, str) else None
        q7 = q7 if isinstance(q7, str) else None
        final = decision_by_id.get(task["run_id"])
        if q2 is not None:
            group["q2_distribution"][q2] += 1
        if q7 is not None:
            group["native_q7_distribution"][q7] += 1
        if final:
            group["successful_decisions"] += 1
            group["final_decision_distribution"][final["decision"]] += 1
        if task["group"] == "evaluation" and q2 is not None and final:
            paired[(task["case_id"], task["repeat"])][task["question_version"]] = q2
            repeats[(task["case_id"], task["question_version"])].append((task["repeat"], q2, q7, final.get("decision") if final else None))
    for error in errors:
        key = error["group"] + "/" + error["question_version"]
        groups[key].setdefault("errors", 0)
        groups[key]["errors"] += 1
    for task in tasks:
        if live:
            groups[task["group"] + "/" + task["question_version"]]["attempted"] += 1
    transitions = Counter()
    for pair in paired.values():
        if all(version in pair for version in VERSIONS):
            transitions[pair[VERSIONS[0]] + " -> " + pair[VERSIONS[1]]] += 1
    stability = {}
    planned_repeats = Counter((task["case_id"], task["question_version"]) for task in tasks if task["group"] == "evaluation")
    for version in VERSIONS:
        eligible = [(key, values) for key, values in repeats.items() if key[1] == version and planned_repeats[key] >= 2 and len(values) == planned_repeats[key]]
        stability[version] = {
            "cases_with_all_repeats_observed": len(eligible),
            "q2_unanimous_cases": sum(len({v[1] for v in values}) == 1 for _, values in eligible),
            "native_q7_unanimous_cases": sum(len({v[2] for v in values}) == 1 for _, values in eligible),
            "final_decision_unanimous_cases": sum(len({v[3] for v in values}) == 1 for _, values in eligible),
        }
    return {
        "schema_version": COMPARISON_SCHEMA, "mode": "live" if live else "prepare",
        "status": "completed_with_errors" if errors else "completed" if live else "prepared",
        "planned_calls": len(tasks), "network_calls": attempts, "attempt_count": attempts,
        "http_response_count": len(responses), "successful_decision_count": len(decisions),
        "error_count": len(errors), "unparseable_response_count": response_parse_errors,
        "response_parse_error_count": sum(error["stage"] == "response_parse" for error in errors),
        "wall_seconds": round(wall_seconds, 3),
        "question_versions": list(VERSIONS), "groups": {key: dict(value) for key, value in sorted(groups.items())},
        "q2_transitions_legacy_to_v2": dict(sorted(transitions.items())),
        "repeat_stability": stability,
        "label_status": "provisional_agent_review_only", "decision_source": "jev_model",
        "accuracy_claim": None, "decision_question": "q7_final_decision",
        "interpretation": "Distributions, transitions and stability describe model behavior; no human-adjudicated gold was supplied, so these are not accuracy results. human_review is a model disposition label.",
    }


def run_comparison(output_dir: str | Path, *, fixture_path: str | Path = FIXTURE_PATH,
                   repeats: int = 2, workers: int = 3, max_calls: int = 200,
                   include_original_six: bool = False, original_dir: str | Path | None = None,
                   disclosure_controls: int = 0, live: bool = False, model: str = DEFAULT_MODEL,
                   timeout: float = 60) -> dict:
    """Persist a controlled comparison; only explicit live mode makes requests."""
    output_dir, fixture_path = Path(output_dir).resolve(), Path(fixture_path).resolve()
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("workers must be an integer from 1 to 4")
    if type(max_calls) is not int or max_calls < 1:
        raise ValueError("max_calls must be positive")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if output_dir.exists() and any((output_dir / name).exists() for name in OUTPUT_NAMES):
        raise ValueError("comparison output already exists; choose a new output directory")
    tasks, requests = prepare_tasks(fixture_path=fixture_path, repeats=repeats,
                                    include_original_six=include_original_six, original_dir=original_dir,
                                    disclosure_controls=disclosure_controls, model=model)
    if len(tasks) > max_calls:
        raise ValueError(f"planned calls {len(tasks)} exceed max_calls={max_calls}; no requests sent")
    api_key = os.getenv("MODELGO_API_KEY") if live else None
    if live and not api_key:
        raise JevConfigurationError("MODELGO_API_KEY is required for --live")
    manifest = {
        "schema_version": COMPARISON_SCHEMA, "mode": "live" if live else "prepare", "model": model,
        "fixture_path": str(fixture_path), "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "case_count": sum(t["group"] == "evaluation" for t in tasks) // (2 * repeats),
        "question_versions": list(VERSIONS), "repeats": repeats, "workers": workers,
        "max_calls": max_calls, "planned_calls": len(tasks), "decision_source": "jev_model",
        "comparison_variable": "q2_fact_support only; question version metadata differs",
        "controlled_pair_validation": "same model, candidate, trace, facts, and all non-Q2 questions",
        "label_source": "provisional_agent_review", "decision_question": "q7_final_decision",
        "tasks": tasks,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_jsonl(output_dir / "requests.jsonl", requests)
    responses, decisions, errors = [], [], []
    for name in ("responses.jsonl", "decisions.jsonl", "errors.jsonl"):
        (output_dir / name).write_text("", encoding="utf-8")
    lock = threading.Lock()
    attempts = 0
    started = time.monotonic()

    def clean(text: str) -> str:
        return text.replace(api_key, "[REDACTED]") if api_key else text

    def execute(task: dict) -> None:
        nonlocal attempts
        observed = False
        identity = _identity(task)
        def observe(reason_id: str, body: str) -> None:
            nonlocal observed
            if reason_id != task["reason_id"]:
                raise ValueError("response observer reason_id mismatch")
            observed = True
            record = dict(identity, response_body=clean(body))
            if record["response_body"] != body:
                record["credential_redacted"] = True
            with lock:
                responses.append(record)
                _append_jsonl(output_dir / "responses.jsonl", record)
        try:
            adapter = JevAdapter(api_key=api_key, model=model, question_version=task["question_version"],
                                 dry_run=False, timeout=timeout, response_observer=observe)
            with lock:
                attempts += 1
            decision = adapter.judge(deepcopy(task["fact_bundle"]))
            if decision.get("reason_id") != task["reason_id"]:
                raise ValueError("decision reason_id mismatch")
            q7 = decision.get("question_choices", {}).get("q7_final_decision")
            if q7 != decision.get("decision"):
                raise ValueError("decision must equal the Jev Q7 response")
            record = dict(identity, decision=decision)
            with lock:
                decisions.append(record)
                _append_jsonl(output_dir / "decisions.jsonl", record)
        except Exception as exc:
            record = dict(identity, stage="response_parse" if observed else "request",
                          error_type=type(exc).__name__, message=clean(str(exc)))
            with lock:
                errors.append(record)
                _append_jsonl(output_dir / "errors.jsonl", record)

    if live:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(execute, task) for task in tasks]
            for future in as_completed(futures):
                future.result()
    summary = summarize_results(tasks, decisions, responses, errors, live=live,
                                attempts=attempts, wall_seconds=time.monotonic() - started)
    summary["artifacts"] = {name.removesuffix(".jsonl").removesuffix(".json"): str(output_dir / name) for name in OUTPUT_NAMES if name != "summary.json"}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fixture", default=str(FIXTURE_PATH))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=200)
    parser.add_argument("--include-original-six", action="store_true")
    parser.add_argument("--original-dir", default=str(ROOT / "runs/2026-11-18-live-validation"))
    parser.add_argument("--disclosure-controls", type=int, default=0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        report = run_comparison(args.output_dir, fixture_path=args.fixture, repeats=args.repeats,
                                workers=args.workers, max_calls=args.max_calls,
                                include_original_six=args.include_original_six, original_dir=args.original_dir,
                                disclosure_controls=args.disclosure_controls, live=args.live,
                                model=args.model, timeout=args.timeout)
    except (ValueError, OSError, JevConfigurationError) as error:
        raise SystemExit(f"comparison failed: {error}") from error
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
