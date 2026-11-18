import json
from pathlib import Path

import pytest

from canonical_data import load_canonical_items
from fact_bundle import build_fact_bundle, load_candidates
from run_rule_baseline import load_lexicon


def test_verified_candidate_builds_auditable_fact_bundle():
    item = load_canonical_items()["i_0001"]
    candidate = {
        "schema_version": "rec-candidate-v2",
        "data_version": "canonical-2026-06-15-v1",
        "reason_id": "r_test_verified",
        "user_id": "u_0001",
        "item_id": "i_0001",
        "exposure_reason": "折叠收纳，卧室整理更方便",
        "generated_reason": "折叠收纳，卧室整理更方便",
        "user_context": {"city": "广州", "interests": ["家居收纳"]},
        "item_attrs_returned": item,
        "attrs_returned_complete": True,
        "promo_computed_in_code": {},
        "ai_disclosure_flag_from_code": True,
        "tool_trace": [{"tool": "get_item", "returned_fields": ["functions", "suitable_scenes"]}],
        "snapshot_at": "2026-11-16T20:00:00+08:00",
        "data_version": "canonical-2026-06-15-v1",
    }
    bundle = build_fact_bundle(candidate, [])

    assert bundle["reason_id"] == "r_test_verified"
    assert bundle["verification_state"] == "verified"
    assert bundle["disclosure"]["flag"] is True
    assert bundle["disclosure"]["required"] is True
    assert bundle["provenance"]["item.functions"].startswith("data/raw/items.csv:")
    assert bundle["tool_trace"]


def test_fact_bundle_preserves_user_facing_exposure_reason():
    candidate = {
        "schema_version": "rec-candidate-v2",
        "data_version": "canonical-2026-06-15-v1",
        "reason_id": "r_exposure",
        "user_id": "u_0001",
        "item_id": "i_0001",
        "exposure_reason": "通勤大容量更好装",
        "generated_reason": "通勤大容量更好装",
        "item_attrs_returned": {},
        "attrs_returned_complete": False,
        "ai_disclosure_flag_from_code": True,
        "tool_trace": [],
    }

    bundle = build_fact_bundle(candidate, [])

    assert bundle["exposure_reason"] == "通勤大容量更好装"
    assert bundle["generated_reason"] == bundle["exposure_reason"]


def test_incomplete_attributes_are_marked_unverifiable():
    candidate = {
        "schema_version": "rec-candidate-v2",
        "data_version": "canonical-2026-06-15-v1",
        "reason_id": "r_test_missing",
        "user_id": "u_0001",
        "item_id": "i_0001",
        "generated_reason": "梅雨季防潮神器",
        "item_attrs_returned": {"category_l1": "家居日用"},
        "attrs_returned_complete": False,
        "ai_disclosure_flag_from_code": True,
        "tool_trace": [{"tool": "get_item", "returned_fields": ["category"]}],
    }
    bundle = build_fact_bundle(candidate, [])

    assert bundle["verification_state"] == "unverifiable"
    assert bundle["coverage"]["missing"]


def test_candidate_loader_reads_jsonl():
    path = Path("tests/fixtures/candidate.jsonl")
    path.parent.mkdir(exist_ok=True)
    path.write_text('{"reason_id":"r1"}\n', encoding="utf-8")
    assert load_candidates(path) == [{"reason_id": "r1"}]


def complete_candidate():
    return {
        "schema_version": "rec-candidate-v2",
        "data_version": "canonical-2026-06-15-v1",
        "reason_id": "r_disclosure_separation",
        "user_id": "u_0001",
        "item_id": "i_0063",
        "exposure_reason": "家庭主食，2.5kg五常大米",
        "generated_reason": "家庭主食，2.5kg五常大米",
        "item_attrs_returned": load_canonical_items()["i_0063"],
        "attrs_returned_complete": True,
        "tool_trace": [{"tool": "get_item", "returned_fields": ["functions", "spec"]}],
        "snapshot_at": "2026-06-15T12:00:00+08:00",
        "ai_disclosure_required": True,
    }


@pytest.mark.parametrize("flag,status,notes", [
    (None, "unknown", ["ai_disclosure_unknown"]),
    (True, "visible", []),
    (False, "missing", ["ai_disclosure_missing"]),
])
def test_disclosure_does_not_change_fact_verification(flag, status, notes):
    candidate = complete_candidate()
    if flag is not None:
        candidate["ai_disclosure_flag_from_code"] = flag
    bundle = build_fact_bundle(candidate, [])

    assert bundle["verification_state"] == "verified"
    assert bundle["coverage"]["complete"] is True
    assert bundle["coverage"]["missing"] == []
    assert bundle["disclosure"] == {"flag": flag, "required": True, "status": status}
    assert bundle["configuration_notes"] == notes


def test_untrusted_status_cannot_claim_disclosure_is_visible():
    candidate = complete_candidate()
    candidate["disclosure_status"] = "visible"
    bundle = build_fact_bundle(candidate, [])

    assert bundle["disclosure"]["flag"] is None
    assert bundle["disclosure"]["status"] == "unknown"
    assert bundle["configuration_notes"] == ["ai_disclosure_unknown"]


@pytest.mark.parametrize("flag", [None, True, False])
def test_missing_facts_remain_unverifiable_regardless_of_disclosure(flag):
    candidate = complete_candidate()
    candidate["item_attrs_returned"].pop("functions")
    if flag is not None:
        candidate["ai_disclosure_flag_from_code"] = flag
    bundle = build_fact_bundle(candidate, [])

    assert bundle["verification_state"] == "unverifiable"
    assert "functions" in bundle["coverage"]["missing"]


def test_no_trace_remains_unverifiable_with_unknown_disclosure():
    candidate = complete_candidate()
    candidate["tool_trace"] = []
    bundle = build_fact_bundle(candidate, [])
    assert bundle["verification_state"] == "unverifiable"
    assert bundle["configuration_notes"] == ["ai_disclosure_unknown"]


@pytest.mark.parametrize("flag", [None, False])
def test_optional_disclosure_keeps_status_without_configuration_action(flag):
    candidate = complete_candidate()
    candidate["ai_disclosure_required"] = False
    if flag is not None:
        candidate["ai_disclosure_flag_from_code"] = flag
    bundle = build_fact_bundle(candidate, [])
    assert bundle["verification_state"] == "verified"
    assert bundle["disclosure"]["required"] is False
    assert bundle["configuration_notes"] == []


@pytest.mark.parametrize("field,value", [
    ("ai_disclosure_flag_from_code", "visible"),
    ("ai_disclosure_flag_from_code", {"visible": True}),
    ("ai_disclosure_required", "false"),
])
def test_disclosure_configuration_rejects_nonboolean_values(field, value):
    candidate = complete_candidate()
    candidate[field] = value
    with pytest.raises(ValueError, match=field):
        build_fact_bundle(candidate, [])
