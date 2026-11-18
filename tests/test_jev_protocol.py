import pytest

from jev_protocol import (
    JEV_QUESTION_SCHEMA_VERSION,
    build_jev_input,
    build_jev_questions,
    parse_jev_answers,
    validate_jev_input,
)


def _bundle():
    return {
        "schema_version": "fact-bundle-v2",
        "reason_id": "r_protocol_0001",
        "user_id": "u_0001",
        "item_id": "i_0001",
        "exposure_reason": "租房收纳，35L折叠盒更省空间",
        "generated_reason": "租房收纳，35L折叠盒更省空间",
        "evidence_fields": ["users.city", "items.spec"],
        "user_context": {
            "city": "广州",
            "city_tier": "一线",
            "climate_zone": "华南",
            "life_stage": "新手妈妈",
            "recent_clicked_item_ids": ["i_9999"],
            "ctr": 0.4,
        },
        "item": {
            "item_id": "i_0001",
            "title": "栖物 可折叠防尘收纳盒 35L 奶油白",
            "brand": "栖物",
            "category_l1": "家居日用",
            "functions": ["折叠", "防尘", "收纳"],
            "spec": "35L 奶油白",
            "suit_audience": "租房人群",
            "price_cents": 5790,
            "stock": 860,
        },
        "promo": {"promo_id": "P010", "applicable": True, "discount_percent": 85},
        "lexicon_hits": [],
        "disclosure": {"flag": True, "required": True},
        "coverage": {"missing": [], "complete": True},
        "verification_state": "verified",
        "rule_features": {"price_mismatch": False, "topic_mismatch": False},
        "provenance": {"item": "data/raw/items.csv:item_id=i_0001"},
        "data_version": "canonical-2026-06-15-v1",
        "agent_version": "rec-agent-v2",
    }


def test_question_schema_has_fixed_q1_to_q7():
    questions = build_jev_questions()

    assert set(questions) == {
        "q1_identity",
        "q2_fact_support",
        "q3_expression_risk",
        "q4_commercial_accuracy",
        "q5_context_relevance",
        "q6_safety_gate",
        "q7_final_decision",
    }
    assert JEV_QUESTION_SCHEMA_VERSION == "jev-questions-v1"
    assert questions["q1_identity"]["type"] == "choice"
    assert "human_review" in questions["q6_safety_gate"]["choices"]
    assert "expose" in questions["q7_final_decision"]["choices"]


def test_jev_input_contains_facts_versions_and_minimal_scene_only():
    payload = build_jev_input(_bundle())

    assert validate_jev_input(payload) == payload
    assert payload["question_schema_version"] == "jev-questions-v1"
    assert payload["candidate"]["item_id"] == "i_0001"
    assert payload["facts"]["item"]["price_cents"] == 5790
    assert payload["facts"]["promo"]["promo_id"] == "P010"
    assert payload["facts"]["scene"]["city"] == "广州"
    assert "recent_clicked_item_ids" not in str(payload)
    assert "ctr" not in str(payload).lower()


def test_jev_input_rejects_forbidden_feedback_and_bad_evidence_paths():
    payload = build_jev_input(_bundle())
    payload["facts"]["feedback_history"] = {"clicked": True}
    with pytest.raises(ValueError, match="forbidden"):
        validate_jev_input(payload)

    payload = build_jev_input(_bundle())
    payload["candidate"]["evidence_fields"] = ["items.not_a_real_field"]
    with pytest.raises(ValueError, match="evidence"):
        validate_jev_input(payload)


def test_jev_input_requires_identity_and_data_version():
    payload = build_jev_input(_bundle())
    del payload["candidate"]["reason_id"]
    with pytest.raises(ValueError, match="reason_id"):
        validate_jev_input(payload)

    payload = build_jev_input(_bundle())
    del payload["trace"]["data_version"]
    with pytest.raises(ValueError, match="data_version"):
        validate_jev_input(payload)


def test_old_three_question_response_is_explicitly_compatible():
    old = {
        "answers": {
            "decision": {"choice": "expose", "confidence": 0.9},
            "risk_type": {"choice": "compliant", "confidence": 0.9},
            "judge_score": {"score": 0.0},
        }
    }

    parsed = parse_jev_answers(old, _bundle())

    assert parsed["protocol_completeness"] == "legacy_3_question"
    assert parsed["decision"] == "expose"
    assert parsed["risk_type"] == "compliant"
    assert parsed["judge_score"] == 0.0


def test_new_q7_response_is_complete():
    payload = {
        "answers": {
            "q1_identity": {"choice": "valid", "confidence": 0.98},
            "q2_fact_support": {"choice": "supported", "evidence": ["items.functions"]},
            "q3_expression_risk": {"choice": "clean"},
            "q4_commercial_accuracy": {"choice": "not_mentioned"},
            "q5_context_relevance": {"choice": "relevant"},
            "q6_safety_gate": {"choice": "pass"},
            "q7_final_decision": {
                "choice": "expose",
                "risk_type": "compliant",
                "score": 0.02,
                "confidence": 0.95,
                "evidence": ["items.functions"],
                "escalated": False,
            },
        }
    }

    parsed = parse_jev_answers(payload, _bundle())

    assert parsed["protocol_completeness"] == "jev-questions-v1"
    assert parsed["decision"] == "expose"
    assert parsed["risk_type"] == "compliant"
    assert parsed["judge_score"] == 0.02
    assert parsed["evidence"] == ["items.functions"]
