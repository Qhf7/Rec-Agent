import json
from pathlib import Path

from fact_bundle import build_fact_bundle, load_candidates
from run_rule_baseline import load_lexicon


def test_verified_candidate_builds_auditable_fact_bundle():
    candidate = {
        "reason_id": "r_test_verified",
        "user_id": "u_0001",
        "item_id": "item_0001",
        "generated_reason": "折叠收纳，卧室整理更方便",
        "user_context": {"city": "杭州", "interests": ["家居收纳"]},
        "item_attrs_returned": {
            "category": "家居日用",
            "functions": ["折叠", "分区收纳"],
            "suitable_scenes": ["卧室整理"],
            "price": 39.9,
        },
        "attrs_returned_complete": True,
        "promo_computed_in_code": {},
        "ai_disclosure_flag_from_code": True,
        "tool_trace": [{"tool": "get_item", "returned_fields": ["functions", "suitable_scenes"]}],
        "snapshot_at": "2026-11-16T20:00:00+08:00",
        "data_version": {"items": "mock-items-v1"},
    }
    bundle = build_fact_bundle(candidate, [])

    assert bundle["reason_id"] == "r_test_verified"
    assert bundle["verification_state"] == "verified"
    assert bundle["disclosure"]["flag"] is True
    assert bundle["disclosure"]["required"] is True
    assert bundle["provenance"]["item.functions"].startswith("items.csv:")
    assert bundle["tool_trace"]


def test_fact_bundle_preserves_user_facing_exposure_reason():
    candidate = {
        "reason_id": "r_exposure",
        "user_id": "u_0001",
        "item_id": "item_0001",
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
        "reason_id": "r_test_missing",
        "generated_reason": "梅雨季防潮神器",
        "item_attrs_returned": {"category": "家居日用"},
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
