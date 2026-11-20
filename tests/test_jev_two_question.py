from copy import deepcopy
from decimal import Decimal

import pytest

from jev_two_question import (
    ATTRACTIVENESS_THRESHOLD, CHOICE_KEYS, RISK_TYPES, TWO_QUESTION_KEYS,
    TWO_QUESTION_POLICY_VERSION, TWO_QUESTION_SCHEMA_VERSION,
    aggregate_two_question_answers, build_two_question_questions, parse_two_question_answers,
)


def answers(index=5, risk_type="compliant"):
    return {
        "risk_type": {"choice": risk_type, "confidence": 0.9},
        "attractiveness_score": {"score": index, "confidence": 0.8},
    }


def parse(value=None, fact_bundle=None):
    return parse_two_question_answers(
        value if value is not None else answers(), fact_bundle or {}, build_two_question_questions(),
        lambda field, bundle: field == "items.functions",
    )


def distribution(**values):
    result = {str(index): 0 for index in range(10)}
    result.update(values)
    return result


def test_exactly_one_six_way_choice_and_ten_level_score_with_one_to_one_hundred_anchors():
    questions = build_two_question_questions()
    assert list(questions) == list(TWO_QUESTION_KEYS) == ["risk_type", "attractiveness_score"]
    assert CHOICE_KEYS == ("risk_type",)
    assert questions["risk_type"]["type"] == "choice"
    assert set(questions["risk_type"]["criteria"]) == set(RISK_TYPES) == {
        "compliant", "absolute_claim", "efficacy_or_medical_claim", "price_misleading",
        "missing_ai_disclosure", "off_topic",
    }
    assert questions["attractiveness_score"]["type"] == "score"
    criteria = questions["attractiveness_score"]["criteria"]
    assert len(criteria) == 10
    assert criteria[0].startswith("映射分1：") and criteria[-1].startswith("映射分100：")
    assert [int(criterion.split("：")[0].replace("映射分", "")) for criterion in criteria] == list(range(1, 101, 11))
    assert "输入candidate" not in questions["risk_type"]["instructions"]
    assert "待判数据" in questions["risk_type"]["instructions"]
    assert "历史曝光点击" in questions["attractiveness_score"]["instructions"]


@pytest.mark.parametrize("score,decision", [
    (1, "rewrite"), (49.99, "rewrite"), (50, "rewrite"), (50.0001, "expose"), (100, "expose"),
    (Decimal("50.000000000000000000001"), "rewrite"),
])
def test_threshold_uses_business_one_to_one_hundred_scale_without_rounding(score, decision):
    result = aggregate_two_question_answers({"risk_type": "compliant"}, score)
    assert result["compliance"] == "Y"
    assert result["decision"] == decision
    assert result["decision_inputs"]["attractiveness_threshold"] == ATTRACTIVENESS_THRESHOLD == 50
    assert result["decision_inputs"]["attractiveness_operator"] == ">"


@pytest.mark.parametrize("risk_type", sorted(RISK_TYPES))
def test_only_compliant_risk_can_expose_even_at_maximum_score(risk_type):
    result = aggregate_two_question_answers({"risk_type": risk_type}, 100)
    assert result["compliance"] == ("Y" if risk_type == "compliant" else "N")
    assert result["decision"] == ("expose" if risk_type == "compliant" else "rewrite")
    assert result["escalated"] is False
    assert result["decision_source"] == "jev_answers_policy"
    assert result["decision_question"] is None and result["decision_confidence"] is None
    assert result["policy_version"] == TWO_QUESTION_POLICY_VERSION


@pytest.mark.parametrize("index,expected", [(0, 1), (4, 45), (5, 56), (9, 100), (4.5, 50.5)])
def test_api_index_is_decoded_once(index, expected):
    result = parse(answers(index))
    assert result["attractiveness_score"] == expected
    assert result["attractiveness_raw_index"] == index
    assert result["attractiveness_expected_index"] == index
    assert result["protocol_completeness"] == TWO_QUESTION_SCHEMA_VERSION
    assert result["question_choices"] == {"risk_type": "compliant"}
    assert result["attractiveness_scale"]["display_min"] == 1
    assert result["attractiveness_scale"]["model_max"] == 9
    assert result["attractiveness_scale"]["mapping"] == "score_index_times_11_plus_one"
    assert "judge_score" not in result
    assert "fact_support_choice" not in result


def test_probability_expectation_overrides_scalar_and_normalizes_service_rounding():
    value = answers(0)
    value["attractiveness_score"]["probabilities"] = distribution(**{"4": 0.49, "5": 0.50})
    result = parse(value)
    assert result["attractiveness_score"] == pytest.approx(1 + 11 * (4 * 0.49 + 5 * 0.50) / 0.99)
    assert sum(result["question_probabilities"]["attractiveness_score"].values()) == pytest.approx(1)
    assert result["decision"] == "expose"
    value["attractiveness_score"]["probabilities"] = distribution(**{"0": 0.5, "9": 0.49})
    result = parse(value)
    assert result["attractiveness_score"] == 50
    assert result["decision"] == "rewrite"


def test_decimal_probability_boundary_remains_fifty():
    value = answers(0)
    value["attractiveness_score"]["probabilities"] = distribution(**{"4": 0.54, "5": 0.45})
    result = parse(value)
    assert result["attractiveness_score"] == 50
    assert result["decision"] == "rewrite"


def test_decision_replays_at_stored_json_precision_for_tiny_score_differences():
    value = answers(4)
    value["attractiveness_score"]["probabilities"] = distribution(**{"4": 0.54, "5": 0.45, "9": 1e-20})
    result = parse(value)
    assert result["attractiveness_score"] == 50
    assert result["decision"] == "rewrite"
    replayed = aggregate_two_question_answers(result["question_choices"], result["attractiveness_score"])
    assert replayed["decision"] == result["decision"]
    assert replayed["decision_inputs"] == result["decision_inputs"]


def test_confidence_and_disclosure_are_diagnostics_not_extra_business_gates():
    value = answers()
    value["risk_type"]["confidence"] = 0.01
    value["attractiveness_score"]["confidence"] = 0.02
    value["risk_type"]["probabilities"] = {key: (0.6 if key == "missing_ai_disclosure" else 0.4 if key == "compliant" else 0) for key in RISK_TYPES}
    result = parse(value, {"disclosure": {"required": True, "flag": False}})
    assert result["confidence"] == 0.01
    assert result["decision"] == "expose"
    assert result["decision_inputs"] == {
        "question_choices": {"risk_type": "compliant"}, "attractiveness_score": 56,
        "attractiveness_threshold": 50, "attractiveness_operator": ">",
    }


def test_evidence_is_checked_for_each_answer_and_deduplicated():
    value = answers()
    for answer in value.values():
        answer["evidence"] = ["items.functions"]
    assert parse(value)["evidence"] == ["items.functions"]
    value["attractiveness_score"]["evidence"] = ["items.nonexistent"]
    with pytest.raises(ValueError, match="evidence"):
        parse(value)


@pytest.mark.parametrize("key", TWO_QUESTION_KEYS)
def test_missing_answers_or_confidence_fail_without_a_fake_decision(key):
    value = answers()
    del value[key]
    with pytest.raises(ValueError, match="exactly"):
        parse(value)
    value = answers()
    del value[key]["confidence"]
    with pytest.raises(ValueError, match="confidence"):
        parse(value)


@pytest.mark.parametrize("key", ["q2_fact_support", "q3_expression_risk", "q5_context_relevance", "q7_final_decision", "compliance"])
def test_extra_old_questions_and_hidden_compliance_question_are_rejected(key):
    value = answers()
    value[key] = {"choice": "supported", "confidence": 0.99}
    with pytest.raises(ValueError, match="exactly"):
        parse(value)


@pytest.mark.parametrize("risk_type", ["missing_evidence", "unsupported_fact", "unknown", True, [], None])
def test_only_six_declared_risks_are_accepted(risk_type):
    with pytest.raises(ValueError, match="risk_type"):
        parse(answers(risk_type=risk_type))
    with pytest.raises(ValueError, match="risk_type"):
        aggregate_two_question_answers({"risk_type": risk_type}, 100)


@pytest.mark.parametrize("score", [0, -1, 100.1, True, "60", float("nan"), float("inf")])
def test_invalid_business_scores_are_rejected(score):
    with pytest.raises(ValueError, match="score"):
        aggregate_two_question_answers({"risk_type": "compliant"}, score)


@pytest.mark.parametrize("index", [-1, 9.1, 100, True, "3", float("nan"), float("inf")])
def test_invalid_api_indexes_are_rejected(index):
    with pytest.raises(ValueError, match="scale"):
        parse(answers(index))


@pytest.mark.parametrize("probabilities", [
    {}, {"0": 1}, {str(index + 1): (1 if index == 4 else 0) for index in range(10)},
    {str(index): (1 if index == 49 else 0) for index in range(100)},
    distribution(**{"4": 0.1}), distribution(**{"4": -0.1, "5": 1.1}),
    distribution(**{"4": float("nan"), "5": 1}),
])
def test_invalid_score_probabilities_are_rejected(probabilities):
    value = answers()
    value["attractiveness_score"]["probabilities"] = probabilities
    with pytest.raises(ValueError, match="probabilit"):
        parse(value)


def test_invalid_risk_probabilities_are_rejected():
    value = answers()
    value["risk_type"]["probabilities"] = {"compliant": 1}
    with pytest.raises(ValueError, match="probabilit"):
        parse(value)


@pytest.mark.parametrize("key", TWO_QUESTION_KEYS)
@pytest.mark.parametrize("confidence", [True, "0.9", -1, 1.1, float("nan"), float("inf"), 10**10000],
                         ids=["boolean", "string", "negative", "above-one", "nan", "inf", "huge-int"])
def test_invalid_confidence_types_and_huge_integers_raise_value_error(key, confidence):
    value = answers()
    value[key]["confidence"] = confidence
    with pytest.raises(ValueError, match="confidence"):
        parse(value)


def test_huge_numbers_and_signalling_decimal_nan_are_rejected_as_validation_errors():
    with pytest.raises(ValueError, match="scale"):
        parse(answers(10**10000))
    for invalid in (10**10000, Decimal("sNaN"), Decimal("1e10000")):
        with pytest.raises(ValueError, match="score"):
            aggregate_two_question_answers({"risk_type": "compliant"}, invalid)
    value = answers()
    value["attractiveness_score"]["probabilities"] = distribution(**{"4": 10**10000})
    with pytest.raises(ValueError, match="probabilit"):
        parse(value)


@pytest.mark.parametrize("key", TWO_QUESTION_KEYS)
@pytest.mark.parametrize("evidence", [None, {}, "items.functions", [None], ["items.nonexistent"]])
def test_invalid_evidence_types_are_rejected(key, evidence):
    value = answers()
    value[key]["evidence"] = evidence
    with pytest.raises(ValueError, match="evidence"):
        parse(value)


@pytest.mark.parametrize("choices", [{}, {"risk_type": "compliant", "q2_fact_support": "supported"}, None])
def test_aggregation_rejects_extra_choice_inputs(choices):
    with pytest.raises(ValueError, match="exactly"):
        aggregate_two_question_answers(choices, 60)


def test_returned_question_definitions_are_independent_objects():
    questions = build_two_question_questions()
    modified = deepcopy(questions)
    modified["risk_type"]["criteria"]["compliant"] = "changed"
    modified["attractiveness_score"]["criteria"][0] = "changed"
    assert build_two_question_questions() == questions
