import pytest

from canonical_data import load_canonical_items, load_canonical_users
from fact_bundle import build_fact_bundle
from mcp_server import get_item
from scripts.migrate_legacy_candidates import (
    migrate_legacy_candidate,
    validate_candidate_contract,
)
from run_rule_baseline import load_lexicon


def test_canonical_candidate_round_trips_through_mcp_and_fact_bundle():
    item = load_canonical_items()["i_0001"]
    candidate = {
        "schema_version": "rec-candidate-v2",
        "data_version": "canonical-2026-06-15-v1",
        "reason_id": "r_canonical_0001",
        "user_id": "u_0001",
        "item_id": "i_0001",
        "exposure_reason": "租房收纳，35L折叠盒更省空间",
        "generated_reason": "租房收纳，35L折叠盒更省空间",
        "evidence_fields": ["users.city", "items.spec"],
        "context_summary": "广州新手妈妈；家居收纳场景",
        "user_context": {"city": "广州", "life_stage": "新手妈妈"},
        "item_attrs_returned": item,
        "promo_computed_in_code": {},
        "attrs_returned_complete": True,
        "ai_disclosure_flag_from_code": True,
        "tool_trace": [{"tool": "get_item", "returned_fields": list(item)}],
    }

    normalized = validate_candidate_contract(candidate)
    bundle = build_fact_bundle(normalized, load_lexicon("data/raw/compliance_lexicon.txt"))
    mcp_item = get_item(normalized["item_id"])

    assert mcp_item["item_id"] == bundle["item_id"] == "i_0001"
    assert mcp_item["title"] == bundle["item"]["title"]
    assert bundle["data_version"] == "canonical-2026-06-15-v1"
    assert all(not value.startswith("items.csv:") for value in bundle["provenance"].values())
    assert "data/raw" in bundle["provenance"]["item"]


def test_legacy_candidate_migration_preserves_reason_id_and_normalizes_fields():
    legacy = {
        "reason_id": "r_legacy_0001",
        "user_id": "u_0001",
        "item_id": "item_0001",
        "generated_reason": "租房收纳，35L折叠盒更省空间",
        "item_attrs_returned": {
            "title": "栖物 可折叠防尘收纳盒 35L 奶油白",
            "brand": "栖物",
            "category": "家居日用",
            "functions": ["折叠", "防尘", "收纳"],
            "price": 57.90,
        },
    }

    migrated = migrate_legacy_candidate(legacy)

    assert migrated["reason_id"] == "r_legacy_0001"
    assert migrated["item_id"] == "i_0001"
    assert migrated["schema_version"] == "rec-candidate-v2"
    assert migrated["data_version"] == "canonical-2026-06-15-v1"
    assert migrated["item_attrs_returned"]["price_cents"] == 5790


def test_legacy_candidate_migration_rejects_identity_conflicts():
    legacy = {
        "reason_id": "r_legacy_bad",
        "user_id": "u_0001",
        "item_id": "item_0001",
        "generated_reason": "不相关商品",
        "item_attrs_returned": {"title": "错误标题", "brand": "栖物"},
    }

    with pytest.raises(ValueError, match="title"):
        migrate_legacy_candidate(legacy)
