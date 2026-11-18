import json
from collections import Counter

from generate_full_candidates import build_full_dataset


def test_full_dataset_has_200_natural_and_100_stress_candidates():
    candidates, labels = build_full_dataset(seed=20261116)

    assert len(candidates) == 300
    assert len(labels) == 300
    assert Counter(row["source"] for row in candidates) == {"natural": 200, "stress": 100}
    assert len({row["reason_id"] for row in candidates}) == 300
    assert {row["reason_id"] for row in candidates} == {row["reason_id"] for row in labels}


def test_full_candidates_have_valid_foreign_keys_and_stratified_splits():
    candidates, labels = build_full_dataset(seed=20261116)
    user_ids = {f"u_{i:04d}" for i in range(1, 201)}
    item_ids = {f"i_{i:04d}" for i in range(1, 201)}

    assert all(row["user_id"] in user_ids for row in candidates)
    assert all(row["item_id"] in item_ids for row in candidates)
    assert {row["split"] for row in candidates} == {"train", "dev", "test"}
    assert all(row["label_source"] == "synthetic_seed_v1" for row in labels)
    assert all(row["tool_trace"] for row in candidates)
    assert all(row["attrs_returned_complete"] is True for row in candidates if row["source"] == "natural")


def test_canonical_templates_use_only_returned_product_facts():
    from generate_full_candidates import _natural_reason, user_snapshot
    from canonical_data import load_canonical_users

    user = load_canonical_users()["u_0001"]
    item = {"functions": ["除湿"], "category_l2": "生活电器", "category_l3": "除湿机", "spec": "12L", "suit_audience": "家庭"}
    reason = _natural_reason(user, item, 0)
    assert "除湿机" in reason and "除湿" in reason
    assert "梅雨" not in reason and "低噪" not in reason
    snapshot = user_snapshot(user)
    assert snapshot["tags"] == user["tags"]
    assert snapshot["active_hours"] == user["active_hours"]
    assert "weather_sensitivity" not in snapshot


def test_promo_snapshot_preserves_scope_and_uses_snapshot_date():
    from canonical_data import load_canonical_items, load_canonical_promos
    from generate_full_candidates import promo_snapshot

    rules = {rule["rule_id"]: rule for rule in load_canonical_promos()}
    item = load_canonical_items()["i_0003"]
    promo = promo_snapshot(item, rules)
    assert promo["scope"] == {"category_l2": ["收纳整理"]}
    assert promo["start"] == "2026-06-01"
    assert promo["end"] == "2026-06-30"
    assert promo["applicable"] is True
    assert promo_snapshot(item, rules, as_of="2026-11-18")["applicable"] is False


def test_all_candidates_preserve_evidence_and_consistent_snapshot_date():
    candidates, labels = build_full_dataset()
    assert all(row["evidence_fields"] for row in candidates)
    assert all(row["snapshot_at"].startswith("2026-06-15") for row in candidates)
    label_by_id = {row["reason_id"]: row for row in labels}
    for candidate in candidates:
        if not candidate["ai_disclosure_flag_from_code"]:
            assert label_by_id[candidate["reason_id"]]["factually_supported"] is True


def test_all_full_and_pilot_fixtures_build_valid_jev_dry_run_requests():
    from fact_bundle import build_fact_bundle
    from generate_pilot_candidates import build_pilot_dataset
    from jev_adapter import JevAdapter
    from run_rule_baseline import load_lexicon

    full, _ = build_full_dataset()
    pilot, _ = build_pilot_dataset()
    lexicon = load_lexicon("data/raw/compliance_lexicon.txt")
    adapter = JevAdapter(api_key="offline-fixture-test", dry_run=True)
    assert len(full + pilot) == 340
    incomplete_count = 0
    for candidate in full + pilot:
        bundle = build_fact_bundle(candidate, lexicon)
        result = adapter.judge(bundle)
        state = json.loads(result["request"]["state"])
        assert state["candidate"]["reason_id"] == candidate["reason_id"]
        assert state["candidate"]["item_id"] == candidate["item_id"]
        for evidence in candidate["evidence_fields"]:
            assert evidence.startswith("items.")
            value = candidate["item_attrs_returned"][evidence.removeprefix("items.")]
            assert value not in (None, "", [])
        if not candidate["attrs_returned_complete"]:
            incomplete_count += 1
            assert bundle["verification_state"] == "unverifiable"
            assert bundle["coverage"]["complete"] is False
            assert "functions" in bundle["coverage"]["missing"]
            assert state["facts"]["verification_state"] == "unverifiable"
    assert incomplete_count > 0
