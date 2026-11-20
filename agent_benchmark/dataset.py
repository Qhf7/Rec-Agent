"""Deterministic, user-disjoint tasks and explicitly constructed trace controls."""
from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import random
from typing import Any

from canonical_data import CANONICAL_SCHEMA_VERSION, load_canonical_items, load_canonical_users
from agent_benchmark.tools import ToolExecutor

SEED = 20261120
DATASET_VERSION = "rec-agent-tasks-v1"
ROOT = Path(__file__).resolve().parents[1]
FACT_REQUIREMENTS = ["profile", "behavior", "history", "session", "item"]


def build_tasks() -> list[dict[str, Any]]:
    """Build 12 development and 8 held-out tasks with disjoint user IDs.

    User pools are derived solely from the checked-in synthetic canonical data
    and approved/shown feedback. Unknown IDs are explicit nonexistent controls.
    Requirements name observed information groups, not output fields: profile,
    behavior, history (including an observed empty history), session, item.
    """
    users = load_canonical_users()
    with (ROOT / "data/recommendation_feedback_history.csv").open(encoding="utf-8-sig", newline="") as stream:
        warm_ids = {r["user_id"] for r in csv.DictReader(stream) if r.get("shown", "").lower() == "true" and r.get("jev_approved", "").lower() == "true" and "2026-05-17" <= r.get("event_date", "") <= "2026-06-15"}
    rng = random.Random(SEED)
    warm = sorted(set(users) & warm_ids)
    cold = sorted(set(users) - warm_ids)
    rng.shuffle(warm)
    rng.shuffle(cold)
    configurations = {"dev": ["warm", "cold_start", "unknown", "empty_search", "tool_timeout", "missing_item_fields"] * 2,
                      "holdout": ["warm", "cold_start", "unknown", "empty_search", "tool_timeout", "missing_item_fields", "warm", "cold_start"]}
    tasks = []
    unknown = 9000
    for split, scenarios in configurations.items():
        for index, scenario in enumerate(scenarios, 1):
            if scenario == "unknown":
                unknown += 1
                uid = f"u_{unknown:04d}"
                assert uid not in users
            else:
                uid = (cold if scenario == "cold_start" else warm).pop()
            tasks.append({"task_id": f"{split}_{index:03d}", "split": split, "user_id": uid, "scenario": scenario,
                          "requirements": ["profile"] if scenario == "unknown" else list(FACT_REQUIREMENTS),
                          "max_tool_calls": 12, "data_source": "canonical_synthetic", "as_of": "2026-06-15"})
    return tasks


def _successful_trace(task: dict) -> dict:
    executor = ToolExecutor(task)
    executor.call("get_user_profile", {"user_id": task["user_id"]})
    recommendations = []
    if task["scenario"] != "unknown":
        for name in ("get_user_behavior", "get_user_recommendation_history"):
            executor.call(name, {"user_id": task["user_id"]})
        executor.call("get_session_context", {})
        search = executor.call("search_items", {"limit": 3})
        if not search["ok"] or not search["result"]:
            search = executor.call("search_items", {"limit": 3})
        # Exact fact text is used for a controlled, supported short reason.
        item = next(x for x in load_canonical_items().values() if x["stock"] > 0 and x.get("functions") and len(x["category_l3"]) + len(x["functions"][0]) + 1 <= 20)
        detail = executor.call("get_item", {"item_id": item["item_id"]})
        if "functions" not in detail.get("result", {}):
            executor.call("get_item", {"item_id": item["item_id"]})
        recommendations = [{"item_id": item["item_id"], "exposure_reason": item["category_l3"] + "，" + item["functions"][0], "evidence_fields": ["items.category_l3", "items.functions"]}]
    for call in executor.calls:
        call["duration_seconds"] = 0.0
    return {"task_id": task["task_id"], "user_id": task["user_id"], "source": "constructed_trace", "calls": executor.calls,
            "final": {"user_id": task["user_id"], "recommendations": recommendations}, "model_calls": 0,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "duration_seconds": 0.0, "budget_exceeded": False}


def frozen_traces(tasks: list[dict]) -> list[dict]:
    """Return 12 controlled development traces, never claimed as live Agent runs.

    The same task may have several controls; trace_id uniquely identifies them.
    Labels describe construction, not a human gold assessment.
    """
    development = [t for t in tasks if t["split"] == "dev"]
    by_scenario = {}
    for task in development:
        by_scenario.setdefault(task["scenario"], task)
    output = []
    def add(trace: dict, label: str):
        trace["trace_id"] = f"constructed_{len(output) + 1:03d}"
        trace["control"] = label
        output.append(trace)
    for scenario in ("warm", "cold_start", "unknown", "empty_search", "tool_timeout", "missing_item_fields"):
        add(_successful_trace(by_scenario[scenario]), "success_" + scenario)
    base = _successful_trace(by_scenario["warm"])
    wrong = deepcopy(base)
    wrong["calls"].insert(0, {"name": "search_items", "arguments": {"limit": "3"}, "result": None, "error": {"type": "ValueError", "message": "invalid type"}, "valid_parameters": False, "duration_seconds": 0.0})
    add(wrong, "invalid_parameter_then_recovery")
    missing = deepcopy(base)
    missing["calls"] = [c for c in missing["calls"] if c["name"] != "get_item"]
    add(missing, "unobserved_item_details")
    hallucinated = deepcopy(base)
    hallucinated["final"]["recommendations"][0]["item_id"] = "i_9999"
    add(hallucinated, "invented_item")
    repeated = deepcopy(base)
    repeated["calls"] += [deepcopy(base["calls"][0]) for _ in range(by_scenario["warm"]["max_tool_calls"] + 1)]
    repeated["budget_exceeded"] = True
    add(repeated, "repeated_calls_over_budget")
    empty = deepcopy(base)
    empty["final"]["recommendations"] = []
    add(empty, "safe_but_incomplete_empty_result")
    wrong_user = deepcopy(base)
    wrong_user["final"]["user_id"] = by_scenario["cold_start"]["user_id"]
    add(wrong_user, "wrong_final_user")
    return output


def freeze_dataset(output: str | Path) -> dict:
    """Write reproducible task/control JSON and a SHA-256 content manifest."""
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    tasks = build_tasks()
    payloads = {"tasks.json": tasks, "frozen_traces.json": frozen_traces(tasks)}
    artifacts = {}
    for name, payload in payloads.items():
        data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        # Timing is diagnostic, excluded from frozen controls for reproducibility.
        if name == "frozen_traces.json":
            for trace in payload:
                for call in trace["calls"]:
                    call["duration_seconds"] = 0.0
            data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        (directory / name).write_bytes(data)
        artifacts[name] = {"sha256": hashlib.sha256(data).hexdigest(), "count": len(payload)}
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("data/raw/users.csv", "data/raw/items.csv", "data/recommendation_feedback_history.csv")}
    manifest = {"dataset_version": DATASET_VERSION, "canonical_version": CANONICAL_SCHEMA_VERSION, "seed": SEED, "source": "canonical_synthetic_and_constructed_controls", "splits": {"dev": 12, "holdout": 8}, "artifacts": artifacts, "source_sha256": sources}
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
