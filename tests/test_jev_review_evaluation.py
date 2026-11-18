import csv
import json
from copy import deepcopy

import pytest

from canonical_data import load_canonical_items
from fact_bundle import build_fact_bundle
from jev_protocol import build_jev_input
from scripts.build_jev_review_evaluation import (
    ANNOTATION_COLUMNS,
    FIXTURE_PATH,
    ORIGINAL_SIX_ITEMS,
    build_evaluation,
    candidate_from_case,
    load_adjudicated_labels,
    load_review_cases,
    require_calibration_labels,
)


def test_frozen_cases_have_disjoint_item_groups_and_no_original_holdout():
    cases = load_review_cases()
    assert len(cases) == 40
    calibration = [case for case in cases if case["split"] == "calibration"]
    holdout = [case for case in cases if case["split"] == "holdout"]
    assert len(calibration) == 24 and len(holdout) == 16
    assert not {case["group_id"] for case in calibration} & {case["group_id"] for case in holdout}
    assert not {case["item_id"] for case in calibration} & {case["item_id"] for case in holdout}
    assert not {case["item_id"] for case in holdout} & ORIGINAL_SIX_ITEMS
    assert len({case["category"] for case in cases}) >= 12


def test_snapshots_are_canonical_or_explicit_omissions_and_never_leak_labels():
    for case in load_review_cases():
        candidate = candidate_from_case(case)
        canonical = load_canonical_items()[case["item_id"]]
        omissions = set(case["omit_item_fields"])
        assert candidate["item_attrs_returned"] == {key: value for key, value in canonical.items() if key not in omissions}
        assert candidate["attrs_returned_complete"] is (not omissions)
        payload = build_jev_input(build_fact_bundle(candidate, []))
        text = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("provisional_q2", "provisional_decision", "provisional_rationale", "provisional_agent_review", "holdout", "calibration"):
            assert forbidden not in text
        assert payload["candidate"]["exposure_reason"] == case["exposure_reason"]


def test_disclosure_variants_preserve_case_identity_and_factual_item_snapshot():
    case = load_review_cases()[0]
    unknown = candidate_from_case(case)
    visible = candidate_from_case(case, ai_disclosure="visible")
    missing = candidate_from_case(case, ai_disclosure="missing")
    assert unknown["reason_id"] == visible["reason_id"] == missing["reason_id"]
    assert unknown["item_attrs_returned"] == visible["item_attrs_returned"] == missing["item_attrs_returned"]
    assert "ai_disclosure_flag_from_code" not in unknown
    assert visible["ai_disclosure_flag_from_code"] is True
    assert missing["ai_disclosure_flag_from_code"] is False


def test_prepare_outputs_blind_source_facts_and_refuses_overwrite(tmp_path, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("evaluation preparation must never call network")
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", no_network)
    manifest = build_evaluation(tmp_path)
    assert manifest["network_calls"] == 0
    assert manifest["eligible_for_threshold_selection"] is False
    with (tmp_path / "human_annotation_template.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 40
    assert all(not row["label_source"] and not row["adjudicated_decision"] for row in rows)
    assert all("rule_features" not in row["facts_json"] and "provisional" not in row["facts_json"] for row in rows)
    assert load_adjudicated_labels(tmp_path / "human_annotation_template.csv", load_review_cases()) == {}
    with pytest.raises(ValueError, match="complete human_adjudicated"):
        require_calibration_labels(tmp_path / "human_annotation_template.csv", load_review_cases())
    with pytest.raises(ValueError, match="already exists"):
        build_evaluation(tmp_path)


def _write_annotations(path, cases, *, source="human_adjudicated", same_reviewer=False, corrupt_reason=False):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_COLUMNS)
        writer.writeheader()
        for case in cases:
            facts = build_jev_input(build_fact_bundle(candidate_from_case(case), []))["facts"]
            facts = {key: value for key, value in facts.items() if key not in {"rule_features", "lexicon_hits"}}
            writer.writerow({
                "case_id": case["case_id"], "item_id": case["item_id"],
                "exposure_reason": case["exposure_reason"] + ("changed" if corrupt_reason else ""),
                "facts_json": json.dumps(facts, ensure_ascii=False), "reviewer1_id": "reviewer-a",
                "reviewer2_id": "reviewer-a" if same_reviewer else "reviewer-b",
                "reviewer1_q2": "supported", "reviewer2_q2": "supported",
                "reviewer1_decision": "expose", "reviewer2_decision": "expose",
                "adjudicator_id": "human-editor", "adjudicated_q2": "supported",
                "adjudicated_decision": "expose", "label_source": source,
            })


@pytest.mark.parametrize("source,same_reviewer,corrupt_reason,match", [
    ("provisional_agent_review", False, False, "human_adjudicated"),
    ("human_adjudicated", True, False, "independent reviewers"),
    ("human_adjudicated", False, True, "differs from frozen"),
])
def test_threshold_calibration_rejects_fake_source_duplicate_reviewers_or_drift(tmp_path, source, same_reviewer, corrupt_reason, match):
    cases = load_review_cases()
    path = tmp_path / "annotations.csv"
    _write_annotations(path, cases, source=source, same_reviewer=same_reviewer, corrupt_reason=corrupt_reason)
    with pytest.raises(ValueError, match=match):
        require_calibration_labels(path, cases)


def test_only_complete_human_calibration_split_is_returned(tmp_path):
    cases = load_review_cases()
    path = tmp_path / "annotations.csv"
    _write_annotations(path, cases)
    labels = require_calibration_labels(path, cases)
    assert len(labels) == 24
    assert all(row["split"] == "calibration" and row["label_source"] == "human_adjudicated" for row in labels.values())
    _write_annotations(path, [case for case in cases if case["split"] == "holdout"])
    with pytest.raises(ValueError, match="complete human_adjudicated"):
        require_calibration_labels(path, cases)


def test_human_annotations_cannot_change_facts_or_duplicate_blank_rows(tmp_path):
    cases = load_review_cases()
    build_evaluation(tmp_path)
    path = tmp_path / "human_annotation_template.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    original_facts = rows[0]["facts_json"]
    rows[0]["facts_json"] = "{}"
    def write_rows():
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ANNOTATION_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
    write_rows()
    with pytest.raises(ValueError, match="facts differ"):
        load_adjudicated_labels(path, cases)
    rows[0]["facts_json"] = original_facts
    rows.append(rows[0])
    write_rows()
    with pytest.raises(ValueError, match="duplicate"):
        load_adjudicated_labels(path, cases)


def test_fixture_rejects_group_or_item_split_leakage(tmp_path):
    document = json.loads(FIXTURE_PATH.read_text())
    document["cases"][1]["split"] = "holdout"
    path = tmp_path / "leak.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="leakage"):
        load_review_cases(path)


def test_omissions_cannot_rewrite_facts_or_remove_identity():
    case = deepcopy(load_review_cases()[0])
    case["omit_item_fields"] = ["item_id"]
    with pytest.raises(ValueError, match="omitted"):
        candidate_from_case(case)
