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


def test_fact_bundle_rejects_unknown_item_and_snapshot_drift():
    item = load_canonical_items()["i_0001"]
    candidate = {
        "schema_version": "rec-candidate-v2",
        "data_version": "canonical-2026-06-15-v1",
        "reason_id": "r_drift",
        "user_id": "u_0001",
        "item_id": "i_0001",
        "exposure_reason": "折叠收纳更省空间",
        "generated_reason": "折叠收纳更省空间",
        "item_attrs_returned": item,
    }

    unknown = dict(candidate, item_id="i_9999")
    with pytest.raises(ValueError, match="unknown item_id"):
        build_fact_bundle(unknown, [])

    drifted_item = dict(item, price_cents=item["price_cents"] + 1)
    with pytest.raises(ValueError, match="price_cents"):
        build_fact_bundle(dict(candidate, item_attrs_returned=drifted_item), [])


def test_legacy_migration_rejects_conflicting_string_version():
    legacy = {
        "reason_id": "r_legacy_version",
        "user_id": "u_0001",
        "item_id": "item_0001",
        "generated_reason": "折叠收纳更省空间",
        "data_version": "other-data-version",
        "item_attrs_returned": {
            "title": "栖物 可折叠防尘收纳盒 35L 奶油白",
            "brand": "栖物",
        },
    }

    with pytest.raises(ValueError, match="data_version"):
        migrate_legacy_candidate(legacy)

def test_canonical_rejects_forged_function_and_version_omission():
    from canonical_data import CANONICAL_SCHEMA_VERSION
    base = {'schema_version':'rec-candidate-v2','data_version':CANONICAL_SCHEMA_VERSION,'reason_id':'r_forged','user_id':'u_0001','item_id':'i_0001','generated_reason':'折叠收纳','item_attrs_returned':{'functions':['治疗失眠']}}
    with pytest.raises(ValueError, match='functions'):
        validate_candidate_contract(base)
    base.pop('item_attrs_returned')
    base.pop('data_version')
    with pytest.raises(ValueError, match='data_version'):
        validate_candidate_contract(base)

def test_coverage_cannot_be_proven_by_trace_field_names():
    from canonical_data import CANONICAL_SCHEMA_VERSION
    base = {'schema_version':'rec-candidate-v2','data_version':CANONICAL_SCHEMA_VERSION,'reason_id':'r_trace','user_id':'u_0001','item_id':'i_0001','generated_reason':'折叠收纳','item_attrs_returned':{'item_id':'i_0001'},'attrs_returned_complete':True,'ai_disclosure_flag_from_code':True,'tool_trace':[{'returned_fields':['functions','category_l1','suit_audience','price_cents']}]}
    bundle = build_fact_bundle(base, [])
    assert bundle['verification_state'] == 'unverifiable'
    assert 'functions' in bundle['coverage']['missing']

def test_legacy_nested_id_and_atomic_migration_failure(tmp_path):
    import json
    from scripts.migrate_legacy_candidates import migrate_jsonl
    base={'reason_id':'r_old','user_id':'u_0001','item_id':'item_0001','generated_reason':'折叠收纳',
          'item_attrs_returned':{'item_id':'item_0001','title':'栖物 可折叠防尘收纳盒 35L 奶油白','brand':'栖物'}}
    assert migrate_legacy_candidate(base)['item_id']=='i_0001'
    source=tmp_path/'source.jsonl'; target=tmp_path/'target.jsonl'
    source.write_text(json.dumps(base)+'\n'+json.dumps(dict(base,item_id='item_9999'))+'\n')
    target.write_text('existing')
    with pytest.raises(ValueError, match='line 2'):
        migrate_jsonl(source,target)
    assert target.read_text()=='existing'

def test_legacy_version_object_is_not_relabelled_canonical():
    legacy={'reason_id':'r_bad_version','user_id':'u_0001','item_id':'item_0001','generated_reason':'收纳',
            'data_version':{'items':'wrong'},'item_attrs_returned':{'title':'栖物 可折叠防尘收纳盒 35L 奶油白','brand':'栖物'}}
    with pytest.raises(ValueError,match='data_version'):
        migrate_legacy_candidate(legacy)

def test_promo_snapshot_cannot_be_forged():
    from generate_full_candidates import build_full_dataset
    candidate=next(row for row in build_full_dataset()[0] if row['promo_computed_in_code'])
    candidate['promo_computed_in_code']['discount_cents']+=1
    with pytest.raises(ValueError,match='promo.discount_cents'):
        validate_candidate_contract(candidate)
