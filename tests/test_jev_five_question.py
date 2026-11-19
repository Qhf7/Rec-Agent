from copy import deepcopy
import itertools
import math

import pytest

from jev_five_question import (
    CHOICE_KEYS, FIVE_QUESTION_KEYS, FIVE_QUESTION_POLICY_VERSION,
    FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION, FIVE_QUESTION_SCHEMA_VERSION,
    aggregate_five_question_answers,
)
from jev_protocol import (
    JEV_QUESTION_SCHEMA_VERSION, V2_JEV_QUESTION_SCHEMA_VERSION,
    build_jev_input, build_jev_questions, parse_jev_answers,
)


def bundle():
    return {
        "schema_version": "fact-bundle-v2", "reason_id": "r_five_0001",
        "user_id": "u_0001", "item_id": "i_0001",
        "exposure_reason": "折叠收纳，整齐随手安排", "generated_reason": "折叠收纳，整齐随手安排",
        "evidence_fields": ["items.functions", "items.title"],
        "user_context": {"city": "广州", "tags": ["家庭采购"], "ctr": .8, "recent_clicked_item_ids": ["i_0002"]},
        "item": {"item_id": "i_0001", "title": "栖物 可折叠防尘收纳盒 35L 奶油白", "functions": ["折叠", "防尘", "收纳"]},
        "promo": {}, "lexicon_hits": [], "coverage": {"missing": [], "complete": True},
        "verification_state": "verified", "rule_features": {}, "provenance": {},
        "disclosure": {"required": True, "flag": None, "status": "unknown"},
        "data_version": "canonical-2026-06-15-v1", "agent_version": "rec-agent-v2",
    }


def good_choices():
    return {"q2_fact_support": "supported", "q3_expression_risk": "clean",
            "q5_context_relevance": "relevant", "risk_type": "compliant"}


def answers(level=3):
    result = {key: {"choice": value, "confidence": .9} for key, value in good_choices().items()}
    result["attractiveness_score"] = {"score": level, "confidence": .8}
    return result


def parse(value=None, **kwargs):
    return parse_jev_answers({"answers": value if value is not None else answers()}, bundle(), **kwargs)


def test_default_is_five_independent_questions_and_frozen_versions_stay_nine():
    questions = build_jev_questions()
    assert JEV_QUESTION_SCHEMA_VERSION == FIVE_QUESTION_SCHEMA_VERSION
    assert list(questions) == list(FIVE_QUESTION_KEYS)
    assert sum(q["type"] == "choice" for q in questions.values()) == 4
    assert questions["attractiveness_score"]["type"] == "score"
    assert len(questions["attractiveness_score"]["criteria"]) == 6
    assert "抬腕可见" in questions["q2_fact_support"]["instructions"]
    previous = build_jev_questions(FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION)
    assert "抬腕可见" not in previous["q2_fact_support"]["instructions"]
    assert len(previous) == 5
    assert build_jev_questions(V2_JEV_QUESTION_SCHEMA_VERSION)["q2_fact_support"] != questions["q2_fact_support"]
    for version in ("jev-questions-v1", V2_JEV_QUESTION_SCHEMA_VERSION, "jev-questions-v2-q2-legacy"):
        old = build_jev_questions(version)
        assert len(old) == 9
        assert "q7_final_decision" in old and "judge_score" in old
        assert "attractiveness_score" not in old
    assert "unsupported_fact" not in build_jev_questions(V2_JEV_QUESTION_SCHEMA_VERSION)["risk_type"]["criteria"]


def test_default_input_retains_fact_allowlist_and_excludes_behavior():
    payload = build_jev_input(bundle())
    assert payload["question_schema_version"] == FIVE_QUESTION_SCHEMA_VERSION
    assert len(payload["questions"]) == 5
    assert payload["facts"]["scene"] == {"city": "广州", "tags": ["家庭采购"]}
    assert "user_id" not in payload["candidate"]
    assert "recent_clicked_item_ids" not in str(payload)
    assert "'ctr':" not in str(payload)


@pytest.mark.parametrize("score,decision", [(0, "rewrite"), (49.999999, "rewrite"), (50, "rewrite"), (50.000001, "expose"), (100, "expose")])
def test_strict_threshold_does_not_round_before_comparison(score, decision):
    result = aggregate_five_question_answers(good_choices(), score)
    assert result["compliance"] == "Y"
    assert result["decision"] == decision
    assert result["decision_inputs"]["attractiveness_score"] == score
    assert result["decision_inputs"]["attractiveness_operator"] == ">"


def test_exposure_requires_every_compliance_choice_and_score_not_just_risk_label():
    variants = [
        ("q2_fact_support", "partial", "rewrite"),
        ("q2_fact_support", "unsupported", "rewrite"),
        ("q2_fact_support", "unverifiable", "human_review"),
        ("q3_expression_risk", "rewriteable", "rewrite"),
        ("q3_expression_risk", "blocking", "block"),
        ("q5_context_relevance", "off_topic", "rewrite"),
        ("q5_context_relevance", "unverifiable", "human_review"),
        ("risk_type", "unsupported_fact", "rewrite"),
        ("risk_type", "missing_evidence", "human_review"),
        ("risk_type", "efficacy_or_medical_claim", "rewrite"),
    ]
    for key, value, decision in variants:
        choices = good_choices()
        choices[key] = value
        result = aggregate_five_question_answers(choices, 100)
        assert result["compliance"] == "N"
        assert result["decision"] == decision, (key, value)
        assert f"{key}:{value}" in result["decision_reasons"]


def test_blocking_precedes_missing_evidence_and_low_attractiveness():
    choices = good_choices()
    choices.update(q2_fact_support="unverifiable", q3_expression_risk="blocking", risk_type="missing_evidence")
    assert aggregate_five_question_answers(choices, 0)["decision"] == "block"


@pytest.mark.parametrize("disclosure,compliance,decision", [
    ({"required": True, "flag": None}, "Y", "expose"),
    ({"required": True, "flag": True}, "Y", "expose"),
    ({"required": True, "flag": False}, "N", "rewrite"),
    ({"required": False, "flag": False}, "Y", "expose"),
])
def test_known_missing_disclosure_is_separate_from_unknown(disclosure, compliance, decision):
    result = aggregate_five_question_answers(good_choices(), 60, disclosure)
    assert result["compliance"] == compliance
    assert result["decision"] == decision
    assert result["decision_inputs"]["required_ai_disclosure_missing"] == (decision == "rewrite")


def test_score_is_attractiveness_not_risk_or_confidence():
    result = parse()
    assert result["attractiveness_score"] == 60
    assert result["attractiveness_expected_level"] == 3
    assert result["confidence"] == .8
    assert result["decision"] == "expose"
    assert result["decision_source"] == "jev_answers_policy"
    assert result["decision_question"] is None
    assert result["decision_confidence"] is None
    assert result["policy_version"] == FIVE_QUESTION_POLICY_VERSION
    assert "judge_score" not in result
    assert "q7_final_decision" not in result["question_choices"]
    value = answers()
    for answer in value.values():
        answer["confidence"] = .01
    assert parse(value)["decision"] == "expose"


def test_probability_expectation_is_authoritative_and_service_rounding_is_normalized():
    value = answers(0)
    value["attractiveness_score"]["probabilities"] = {"0": 0, "1": 0, "2": .49, "3": .50, "4": 0, "5": 0}
    result = parse(value)
    assert result["attractiveness_score"] == pytest.approx((2*.49 + 3*.50)/.99*20)
    assert sum(result["question_probabilities"]["attractiveness_score"].values()) == pytest.approx(1)
    assert result["decision"] == "expose"
    value["attractiveness_score"]["probabilities"] = {"0": 0, "1": 0, "2": .5, "3": .5, "4": 0, "5": 0}
    assert parse(value)["attractiveness_score"] == 50
    assert parse(value)["decision"] == "rewrite"


def test_decimal_probability_boundary_is_not_promoted_by_binary_float_rounding():
    value = answers(0)
    value["attractiveness_score"]["probabilities"] = {
        "0": 0, "1": 0, "2": .55, "3": .4, "4": .05, "5": 0,
    }
    result = parse(value)
    assert result["attractiveness_score"] == 50
    assert result["decision"] == "rewrite"


@pytest.mark.parametrize("key", FIVE_QUESTION_KEYS)
def test_missing_answers_or_confidence_are_errors_not_business_dispositions(key):
    value = answers()
    del value[key]
    with pytest.raises(ValueError, match="exactly"):
        parse(value, expected_protocol=FIVE_QUESTION_SCHEMA_VERSION)
    value = answers()
    del value[key]["confidence"]
    with pytest.raises(ValueError, match="confidence"):
        parse(value)


def test_additional_q7_and_legacy_protocol_mismatch_are_rejected():
    value = answers()
    value["q7_final_decision"] = {"choice": "expose", "confidence": .99}
    with pytest.raises(ValueError, match="exactly"):
        parse(value)
    with pytest.raises(ValueError, match="protocol"):
        parse(expected_protocol=V2_JEV_QUESTION_SCHEMA_VERSION)


@pytest.mark.parametrize("score", [-1, 5.001, 60, True, "3", float("nan"), float("inf")])
def test_wrong_score_scale_and_nonfinite_values_rejected(score):
    value = answers(score)
    with pytest.raises(ValueError, match="scale"):
        parse(value)


@pytest.mark.parametrize("probabilities", [
    {}, {"0": 1}, {str(n): .1 for n in range(6)},
    {"0": 0, "1": 0, "2": -0.1, "3": 1.1, "4": 0, "5": 0},
    {"0": 0, "1": 0, "2": float("nan"), "3": 1, "4": 0, "5": 0},
])
def test_invalid_score_probability_keys_values_and_totals_rejected(probabilities):
    value = answers()
    value["attractiveness_score"]["probabilities"] = probabilities
    with pytest.raises(ValueError, match="probabilit"):
        parse(value)


def test_transmitted_evidence_is_validated_for_each_question():
    value = answers()
    value["q2_fact_support"]["evidence"] = ["items.functions"]
    result = parse(value)
    assert result["evidence"] == ["items.functions"]
    value["risk_type"]["evidence"] = ["items.nonexistent"]
    with pytest.raises(ValueError, match="evidence"):
        parse(value)


def test_all_valid_choice_combinations_have_transparent_total_disposition():
    questions = build_jev_questions()
    for values in itertools.product(*(questions[key]["criteria"] for key in CHOICE_KEYS)):
        choices = dict(zip(CHOICE_KEYS, values))
        result = aggregate_five_question_answers(choices, 75)
        can_expose = choices == good_choices()
        assert (result["decision"] == "expose") is can_expose
        assert (result["compliance"] == "Y") is can_expose
        assert result["escalated"] == (result["decision"] == "human_review")
