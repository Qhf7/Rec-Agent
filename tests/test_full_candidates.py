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
