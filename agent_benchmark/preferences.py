"""Prepare blinded human preference pairs; no automatic labels or DPO training.

Only independently completed live development traces are eligible. Annotators
see the same canonical context and original final JSON in randomized A/B order.
Policy names, source paths and verification details remain in a separate audit
manifest. Human labels are collection data, not independent quality gold.

python -m agent_benchmark.preferences prepare --run-root runs/agent-benchmark-v1 --output runs/preferences
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import random
from typing import Any

from canonical_data import load_canonical_items, load_canonical_users
from agent_benchmark.dataset import build_tasks
from agent_benchmark.metrics import evaluate_trace
from scripts.strict_json_output import strict_json_loads

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261120
VERSION = "rec-agent-human-preferences-v1"
COLUMNS = ["pair_id", "preference", "reviewer_id", "reason", "status"]
USER_FIELDS = ("user_id", "city", "city_tier", "climate_zone", "life_stage", "preferred_categories", "tags", "active_hours", "price_sensitivity", "recent_cart_item_ids", "recent_order_item_ids", "last_search_terms")
ITEM_FIELDS = ("item_id", "title", "brand", "category_l1", "category_l2", "category_l3", "functions", "material", "spec", "suit_audience", "suit_season", "efficacy_claims_allowed", "qualifications", "price_cents", "stock")


def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _task_lookup(tasks: list[dict]) -> dict[str, dict]:
    lookup = {task["task_id"]: task for task in tasks}
    if len(lookup) != len(tasks):
        raise ValueError("duplicate task IDs")
    dev = {t["user_id"] for t in tasks if t["split"] == "dev"}
    holdout = {t["user_id"] for t in tasks if t["split"] == "holdout"}
    if dev & holdout:
        raise ValueError("holdout user leakage")
    return lookup


def _load_trace(path: Path, task: dict, policy: str) -> tuple[dict, str]:
    trace = strict_json_loads(path.read_text(encoding="utf-8"))
    if task.get("split") != "dev" or trace.get("split") == "holdout" or str(trace.get("task_id", "")).startswith("holdout"):
        raise ValueError("holdout traces are forbidden in preference preparation")
    if trace.get("task_id") != task["task_id"] or trace.get("user_id") != task["user_id"]:
        raise ValueError("trace/task identity mismatch")
    if trace.get("source") != "live_agent" or trace.get("control"):
        raise ValueError("preference pairs require actual live Agent traces")
    if trace.get("policy") != policy:
        raise ValueError("trace policy/path identity mismatch")
    calls = trace.get("model_calls")
    if not isinstance(calls, list) or not any(isinstance(c, dict) and isinstance(c.get("message"), dict) for c in calls):
        raise ValueError("missing recorded model output provenance")
    if trace.get("final") is not None:
        recorded_finals = []
        for call in calls:
            content = call.get("message", {}).get("content") if isinstance(call, dict) else None
            if not isinstance(content, str):
                continue
            try:
                value = strict_json_loads(content)
            except ValueError:
                continue
            if isinstance(value, dict):
                recorded_finals.append(value.get("final", value))
        if trace["final"] not in recorded_finals:
            raise ValueError("final answer absent from recorded model responses")
    return trace, _sha(path)


def _visible_trace(trace: dict) -> dict:
    visible = deepcopy(trace)
    for call in visible.get("calls", []):
        observation = call.get("model_observation")
        if observation is not None:
            call["result"] = observation.get("result") if isinstance(observation, dict) and "ok" in observation else observation
    return visible


def prepare_pairs(run_root: str | Path, output: str | Path, *, tasks: list[dict] | None = None, seed: int = SEED) -> dict:
    """Prepare unlabeled dev pairs and audit manifest, never fabricate labels.

    Both policies must independently complete the common task using facts
    visible to that model. Identical final answers and incomplete runs are
    excluded. Different tool trajectories do not become annotator identities.
    """
    run_root, directory = Path(run_root).resolve(), Path(output).resolve()
    tasks = build_tasks() if tasks is None else tasks
    lookup = _task_lookup(tasks)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("preference output directory must be empty")
    policies = ("adaptive", "budgeted")
    sources: dict[str, dict[str, tuple[Path, dict, str]]] = {}
    # Scan the named development folders only; a misplaced holdout is rejected.
    for policy in policies:
        folder = run_root / ("dev-" + policy)
        for path in sorted(folder.glob("*/trace.json")):
            identity = path.parent.name
            task = lookup.get(identity)
            if task is None:
                raise ValueError("unknown task in development trace folder")
            trace, digest = _load_trace(path, task, policy)
            sources.setdefault(identity, {})[policy] = (path.resolve(), trace, digest)
    users, items = load_canonical_users(), load_canonical_items()
    rng = random.Random(seed)
    pairs, audit, excluded = [], [], []
    for task_id in sorted(sources):
        task, candidates = lookup[task_id], sources[task_id]
        if set(candidates) != set(policies):
            excluded.append({"task_id": task_id, "reason": "missing_policy_trace"})
            continue
        if any(not evaluate_trace(task, trace)["task_completed"] or not evaluate_trace(task, _visible_trace(trace))["task_completed"]
               for _, trace, _ in candidates.values()):
            excluded.append({"task_id": task_id, "reason": "independent_completion_check_failed"})
            continue
        if _bytes(candidates[policies[0]][1]["final"]) == _bytes(candidates[policies[1]][1]["final"]):
            excluded.append({"task_id": task_id, "reason": "identical_final_answers"})
            continue
        pair_id = "pair_" + hashlib.sha256(_bytes({"task_id": task_id, "hashes": sorted(value[2] for value in candidates.values())})).hexdigest()[:16]
        ordered = list(policies)
        rng.shuffle(ordered)
        ids = sorted({rec["item_id"] for _, trace, _ in candidates.values() for rec in trace["final"]["recommendations"]})
        user = users.get(task["user_id"], {})
        context = {"user": {key: deepcopy(user[key]) for key in USER_FIELDS if key in user},
                   "scenario_date": task.get("as_of", "2026-06-15"),
                   "products": {iid: {key: deepcopy(items[iid][key]) for key in ITEM_FIELDS if key in items[iid]} for iid in ids},
                   "request": "请选择更适合该用户、事实有依据且自然清晰的商品推荐；综合选品、曝光理由、真实性和表达，难分优劣可选tie。"}
        pair = {"pair_id": pair_id, "context": context,
                "candidate_A": deepcopy(candidates[ordered[0]][1]["final"]),
                "candidate_B": deepcopy(candidates[ordered[1]][1]["final"])}
        pairs.append(pair)
        audit.append({"pair_id": pair_id, "task_id": task_id, "user_id": task["user_id"], "split": "dev", "pair_sha256": hashlib.sha256(_bytes(pair)).hexdigest(),
                      "sources": {letter: {"policy": policy, "path": str(candidates[policy][0]), "sha256": candidates[policy][2]}
                                  for letter, policy in zip(("A", "B"), ordered)}})
    directory.mkdir(parents=True, exist_ok=True)
    pairs_path = directory / "blind_pairs.jsonl"
    pairs_path.write_text("".join(_bytes(pair).decode() + "\n" for pair in pairs), encoding="utf-8")
    with (directory / "annotation_template.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({"pair_id": pair["pair_id"], "preference": "", "reviewer_id": "", "reason": "", "status": "pending"} for pair in pairs)
    manifest = {"schema_version": VERSION, "seed": seed, "split": "dev", "label_status": "pending_human_review",
                "pair_count": len(pairs), "pair_file_sha256": _sha(pairs_path), "run_root": str(run_root),
                "source_sha256": {name: _sha(ROOT / name) for name in ("data/raw/users.csv", "data/raw/items.csv", "data/recommendation_feedback_history.csv")},
                "tasks_sha256": hashlib.sha256(_bytes(tasks)).hexdigest(), "tasks": tasks, "pairs": audit, "excluded": excluded,
                "limitations": ["Labels must be supplied by human reviewers; no Jev/LLM default preference.",
                                 "Development-only pairs are not independent human gold or evidence of online gains.",
                                 "Shared canonical context permits output comparison; policies had different observed tool trajectories.",
                                 "A/B blinding hides policy identities but output length/style can still differ."]}
    _write(directory / "manifest.json", manifest)
    return manifest


def validate_annotations(path: str | Path, pairs: str | Path, manifest: str | Path) -> dict:
    """Audit manual labels and return accepted chosen/rejected records.

    CSV status must be explicitly human_reviewed, with reviewer ID and reason.
    Pending rows remain unlabeled; ties are audited but excluded from training.
    This records a reviewer's declaration, not external proof of human origin.
    No training file is written by this function.
    """
    path, pairs_path, manifest_path = Path(path), Path(pairs), Path(manifest)
    metadata = strict_json_loads(manifest_path.read_text(encoding="utf-8"))
    if metadata.get("schema_version") != VERSION or metadata.get("split") != "dev":
        raise ValueError("unsupported or non-development preference manifest")
    if _sha(pairs_path) != metadata["pair_file_sha256"]:
        raise ValueError("blind pair file hash drift")
    for name, digest in metadata["source_sha256"].items():
        if _sha(ROOT / name) != digest:
            raise ValueError("canonical source hash drift")
    tasks = metadata["tasks"]
    if hashlib.sha256(_bytes(tasks)).hexdigest() != metadata["tasks_sha256"]:
        raise ValueError("task manifest hash drift")
    lookup = _task_lookup(tasks)
    pair_rows = [strict_json_loads(line) for line in pairs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {row["pair_id"]: row for row in pair_rows}
    audits = {row["pair_id"]: row for row in metadata["pairs"]}
    if len(by_id) != len(pair_rows) or set(by_id) != set(audits) or len(by_id) != metadata["pair_count"]:
        raise ValueError("pair identity mismatch")
    for pair_id, audit in audits.items():
        pair = by_id[pair_id]
        if hashlib.sha256(_bytes(pair)).hexdigest() != audit["pair_sha256"]:
            raise ValueError("pair record hash drift")
        task = lookup[audit["task_id"]]
        if audit.get("split") != "dev" or task["split"] != "dev" or audit["user_id"] != task["user_id"]:
            raise ValueError("holdout or identity mismatch in pair audit")
        for letter, source in audit["sources"].items():
            source_path = Path(source["path"])
            if _sha(source_path) != source["sha256"]:
                raise ValueError("source trace hash drift")
            trace, _ = _load_trace(source_path, task, source["policy"])
            if trace.get("final") != pair["candidate_" + letter] or not evaluate_trace(task, trace)["task_completed"]:
                raise ValueError("candidate differs from verified source final")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != COLUMNS:
            raise ValueError("annotation CSV fields do not match the template")
        annotations = list(reader)
    seen, accepted, ties, pending = set(), [], 0, 0
    for row in annotations:
        pair_id = row["pair_id"]
        if pair_id not in by_id or pair_id in seen:
            raise ValueError("unknown or duplicate annotated pair ID")
        seen.add(pair_id)
        status, preference = row["status"].strip(), row["preference"].strip()
        if status == "pending" and not preference and not row["reviewer_id"].strip() and not row["reason"].strip():
            pending += 1
            continue
        if status != "human_reviewed" or preference not in ("A", "B", "tie") or not row["reviewer_id"].strip() or not row["reason"].strip():
            raise ValueError("labels require explicit human_reviewed provenance, reviewer, reason and A/B/tie")
        if preference == "tie":
            ties += 1
            continue
        pair = by_id[pair_id]
        other = "B" if preference == "A" else "A"
        accepted.append({"pair_id": pair_id, "split": "dev", "label_source": "human_reviewed",
                         "reviewer_id": row["reviewer_id"].strip(), "reason": row["reason"].strip(),
                         "prompt": deepcopy(pair["context"]), "chosen": deepcopy(pair["candidate_" + preference]), "rejected": deepcopy(pair["candidate_" + other]),
                         "annotation_file_sha256": _sha(path), "pair_sha256": audits[pair_id]["pair_sha256"]})
    return {"pair_count": len(by_id), "annotation_rows": len(annotations), "pending_count": pending + len(by_id) - len(seen),
            "tie_count": ties, "accepted_count": len(accepted), "accepted": accepted, "label_source": "human_reviewed" if accepted or ties else None,
            "limitation": "Declared human review, development preference collection; not independent gold and not DPO training."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--run-root", required=True)
    prepare.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--annotations", required=True)
    validate.add_argument("--pairs", required=True)
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--output")
    args = parser.parse_args()
    if args.command == "prepare":
        report = prepare_pairs(args.run_root, args.output)
        report = {key: report[key] for key in ("pair_count", "label_status", "split")}
    else:
        report = validate_annotations(args.annotations, args.pairs, args.manifest)
        if args.output and report["accepted"]:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                raise ValueError("refusing to overwrite existing preference export")
            output.write_text("".join(_bytes(row).decode() + "\n" for row in report["accepted"]), encoding="utf-8")
        report = {key: value for key, value in report.items() if key != "accepted"}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
