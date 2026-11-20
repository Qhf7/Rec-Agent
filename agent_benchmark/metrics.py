"""Deterministic task verification independent from any model judge."""
from __future__ import annotations

from typing import Any
from canonical_data import load_canonical_items, load_canonical_users
from recommendation_copy import validate_reason_text
from agent_benchmark.tools import SCENARIO_DATE, validate_arguments
from mcp_server import get_user_recommendation_history


def _result(call: dict) -> Any:
    value = call.get("result")
    if isinstance(value, dict) and "ok" in value and "result" in value:
        return value["result"] if value["ok"] else None
    return value


def evaluate_trace(task: dict, trace: dict) -> dict[str, Any]:
    """Verify final structure and observed information, never model assertions.

    Five fixed fact groups are available: profile requires a successful target
    profile with city/life_stage matching canonical data; behavior requires
    canonical preferences and cart IDs; history requires the target user's
    observed history status/count at the fixed date (empty history counts);
    session requires scenario_date/timezone; item requires every recommended
    product to have successful get_item observations supporting its evidence.
    Unknown-user tasks require only an observed found=false profile. Search
    results and final evidence_fields alone never satisfy item coverage.

    valid_tool_calls counts independently validated argument sets, including
    valid calls that received an injected timeout. successful_tool_calls is
    separate. Task completion also requires full required coverage, a valid
    final result, matching trace identity, and no tool-budget overrun. Invalid
    parameter recovery is measured without automatically failing completion.
    Evidence verification checks observed nonempty canonical field values; it
    does not claim a general semantic proof of advertising copy.
    """
    users = load_canonical_users()
    items = load_canonical_items()
    uid = task["user_id"]
    known = uid in users
    errors: list[str] = []
    calls = trace.get("calls", [])
    if not isinstance(calls, list):
        calls = []
        errors.append("calls_not_array")
    facts = {"profile": False, "behavior": False, "history": False, "session": False, "item": False}
    observations: dict[str, list[dict]] = {}
    observed_profile: dict = {}
    valid = successful = 0
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            errors.append(f"call_{index}:invalid_record")
            continue
        try:
            validate_arguments(call.get("name"), call.get("arguments"), task)
        except (ValueError, TypeError) as exc:
            errors.append(f"call_{index}:invalid_parameters:{exc}")
            continue
        valid += 1
        value = _result(call)
        if call.get("error") or value is None:
            continue
        successful += 1
        if not isinstance(value, dict):
            continue
        name = call["name"]
        same_user = value.get("user_id") == uid
        if name == "get_user_profile" and same_user:
            if not known and value.get("found") is False:
                facts["profile"] = True
            elif known and value.get("found") is True and all(value.get(k) == users[uid].get(k) for k in ("city", "life_stage")):
                facts["profile"] = True
                observed_profile = value
        elif name == "get_user_behavior" and known and same_user and value.get("found") is True:
            facts["behavior"] |= all(k in value and value[k] == users[uid].get(k) for k in ("preferred_categories", "recent_cart_item_ids"))
        elif name == "get_user_recommendation_history" and known and same_user and value.get("found") is True:
            expected = get_user_recommendation_history(**call["arguments"])
            facts["history"] |= all(key in value and value[key] == expected[key] for key in ("as_of", "event_count", "clicked_count", "history_status", "history_available"))
        elif name == "get_session_context":
            facts["session"] |= value.get("scenario_date") == SCENARIO_DATE and value.get("timezone") == "Asia/Shanghai"
        elif name == "get_item" and value.get("found") is True:
            iid = call["arguments"]["item_id"]
            canonical = items.get(iid)
            if canonical and value.get("item_id") == iid and value.get("stock") == canonical["stock"] and value.get("title") == canonical["title"]:
                observations.setdefault(iid, []).append(value)
    final = trace.get("final")
    final_errors = []
    if not isinstance(final, dict):
        final_errors.append("final_not_object")
        final = {}
    if final.get("user_id") != uid:
        final_errors.append("wrong_final_user")
    recs = final.get("recommendations")
    if not isinstance(recs, list):
        final_errors.append("recommendations_not_array")
        recs = []
    if known and not 1 <= len(recs) <= 3:
        final_errors.append("known_user_requires_one_to_three_recommendations")
    if not known and recs:
        final_errors.append("unknown_user_requires_empty_recommendations")
    item_coverage = bool(recs)
    seen = set()
    scene_fields = {"city", "city_tier", "climate_zone", "life_stage", "tags", "active_hours"}
    for index, rec in enumerate(recs):
        if not isinstance(rec, dict):
            final_errors.append(f"recommendation_{index}:not_object")
            item_coverage = False
            continue
        iid = rec.get("item_id")
        if not isinstance(iid, str) or iid not in items:
            final_errors.append(f"recommendation_{index}:unknown_item")
            item_coverage = False
            continue
        if iid in seen:
            final_errors.append(f"recommendation_{index}:duplicate_item")
        seen.add(iid)
        if items[iid]["stock"] <= 0:
            final_errors.append(f"recommendation_{index}:out_of_stock")
        try:
            validate_reason_text(rec.get("exposure_reason"))
        except ValueError as exc:
            final_errors.append(f"recommendation_{index}:invalid_reason:{exc}")
        evidence = rec.get("evidence_fields")
        if not isinstance(evidence, list) or not 2 <= len(evidence) <= 6 or any(not isinstance(p, str) for p in evidence):
            final_errors.append(f"recommendation_{index}:invalid_evidence_fields")
            item_coverage = False
            continue
        if len(set(evidence)) != len(evidence) or not any(p.startswith("items.") for p in evidence):
            final_errors.append(f"recommendation_{index}:invalid_evidence_paths")
            item_coverage = False
        if iid not in observations:
            final_errors.append(f"recommendation_{index}:item_details_not_observed")
            item_coverage = False
        for path in evidence:
            prefix, _, field = path.partition(".")
            if prefix == "items":
                supported = any(field in observed and observed[field] not in (None, "", []) and observed[field] == items[iid].get(field) for observed in observations.get(iid, []))
            elif prefix in ("users", "user_context") and field in scene_fields and known:
                supported = field in observed_profile and observed_profile[field] not in (None, "", []) and observed_profile[field] == users[uid].get(field)
            else:
                supported = False
            if not supported:
                final_errors.append(f"recommendation_{index}:unobserved_evidence:{path}")
                item_coverage = False
    facts["item"] = item_coverage
    required = list(dict.fromkeys(task.get("requirements", ["profile"])))
    covered = [key for key in required if facts.get(key, False)]
    coverage = len(covered) / len(required) if required else 1.0
    identity_valid = trace.get("task_id") == task["task_id"] and trace.get("user_id") == uid
    if not identity_valid:
        errors.append("trace_identity_mismatch")
    budget_exceeded = bool(trace.get("budget_exceeded")) or len(calls) > task.get("max_tool_calls", 12)
    if budget_exceeded:
        errors.append("tool_budget_exceeded")
    errors.extend(final_errors)
    for requirement in required:
        if not facts.get(requirement, False):
            errors.append(f"missing_fact:{requirement}")
    return {"task_id": task["task_id"], "task_completed": not final_errors and identity_valid and not budget_exceeded and coverage == 1.0,
            "valid_tool_calls": valid, "attempted_tool_calls": len(calls), "successful_tool_calls": successful,
            "required_fact_count": len(required), "covered_fact_count": len(covered), "fact_coverage": coverage,
            "covered_facts": covered, "final_valid": not final_errors, "budget_exceeded": budget_exceeded, "errors": errors}
