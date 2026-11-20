from copy import deepcopy
import pytest
from agent_benchmark.disagreements import trajectory_agreement


def row(case, kind, choice="yes", status="ok"):
    value = {"case_id": case, "kind": kind, "repeat": 1, "status": status,
             "input_sha256": case, "reference": {"task_completed": "yes"}}
    if status == "ok":
        value["choices"] = {"task_completed": choice}
    return value


def test_agreement_does_not_make_jev_the_reference():
    result = trajectory_agreement([row("a", "jev", "no"), row("a", "other"),
                                   row("b", "jev"), row("b", "other", status="error")])
    value = result["comparisons"]["other"]
    assert value["planned_pairs"] == 2 and value["valid_pairs"] == 1
    assert value["all_answers_equal_rate_valid"] == 0
    assert value["per_question"]["task_completed"]["model_only_matches_reference"] == 1
    assert len(value["missing_pairs"]) == 1


def test_pair_hash_drift_and_duplicates_rejected():
    a, b = row("a", "jev"), row("a", "other")
    b["input_sha256"] = "changed"
    with pytest.raises(ValueError, match="inputs differ"):
        trajectory_agreement([a, b])
    with pytest.raises(ValueError, match="duplicate"):
        trajectory_agreement([a, a])
