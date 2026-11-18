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
        "risk_type",
        "judge_score",
    }
    assert JEV_QUESTION_SCHEMA_VERSION == "jev-questions-v2"
    assert questions["q1_identity"]["type"] == "choice"
    assert "human_review" in questions["q6_safety_gate"]["criteria"]
    assert "expose" in questions["q7_final_decision"]["criteria"]


def test_jev_input_contains_facts_versions_and_minimal_scene_only():
    payload = build_jev_input(_bundle())

    assert validate_jev_input(payload) == payload
    assert payload["question_schema_version"] == "jev-questions-v2"
    assert payload["candidate"]["item_id"] == "i_0001"
    assert payload["facts"]["item"]["price_cents"] == 5790
    assert payload["facts"]["promo"]["promo_id"] == "P010"
    assert payload["facts"]["scene"]["city"] == "广州"
    assert "user_id" not in payload["candidate"]
    assert "user_id" not in payload["trace"]
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


def test_jev_input_rejects_cross_layer_identity_version_and_unknown_fields():
    payload = build_jev_input(_bundle())
    payload["trace"]["item_id"] = "i_0002"
    with pytest.raises(ValueError, match="item_id"):
        validate_jev_input(payload)

    payload = build_jev_input(_bundle())
    payload["trace"]["data_version"] = "other-version"
    with pytest.raises(ValueError, match="data_version"):
        validate_jev_input(payload)

    payload = build_jev_input(_bundle())
    payload["facts"]["rule_features"]["unknown_signal"] = True
    with pytest.raises(ValueError, match="unknown"):
        validate_jev_input(payload)


def test_jev_parser_rejects_invalid_final_choices():
    payload = {
        "answers": {
            "q1_identity": {"choice": "valid"},
            "q2_fact_support": {"choice": "supported"},
            "q3_expression_risk": {"choice": "clean"},
            "q4_commercial_accuracy": {"choice": "not_mentioned"},
            "q5_context_relevance": {"choice": "relevant"},
            "q6_safety_gate": {"choice": "pass"},
            "q7_final_decision": {"choice": "unknown", "risk_type": "compliant", "score": 0.1},
        }
    }
    with pytest.raises(ValueError, match="decision"):
        parse_jev_answers(payload, _bundle())


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

def test_official_wire_uses_supported_primitives_only():
    for question in build_jev_questions().values():
        assert set(question) == {'type', 'instructions', 'criteria'}
        assert question['type'] in {'choice', 'score'}
        assert isinstance(question['criteria'], dict if question['type'] == 'choice' else list)

def test_scalar_q1_q7_answers_parse_with_separate_risk_and_score():
    answers = {key:{'choice':next(iter(q['criteria'])), 'confidence':.96}
               for key,q in build_jev_questions().items() if q['type']=='choice'}
    answers['judge_score'] = {'score':1,'probabilities':{'0':0,'1':1,'2':0},'confidence':.96}
    parsed = parse_jev_answers({'answers':answers}, _bundle())
    assert parsed['judge_score'] == .5
    assert parsed['protocol_completeness'] == JEV_QUESTION_SCHEMA_VERSION

@pytest.mark.parametrize('confidence', [float('nan'), float('inf'), -.1, 1.1, True])
def test_invalid_confidence_is_rejected(confidence):
    response={'answers': {'decision':{'choice':'expose','confidence':confidence},
                         'risk_type':{'choice':'compliant','confidence':.9},
                         'judge_score':{'score':0}}}
    with pytest.raises(ValueError, match='confidence'):
        parse_jev_answers(response, _bundle())

def test_evidence_must_exist_in_transmitted_snapshot():
    payload=build_jev_input(_bundle())
    payload['candidate']['evidence_fields']=['items.qualifications']
    with pytest.raises(ValueError, match='evidence'):
        validate_jev_input(payload)

def _scalar_response():
    answers={key:{'choice':next(iter(q['criteria'])),'confidence':.99}
             for key,q in build_jev_questions().items() if q['type']=='choice'}
    answers['judge_score']={'score':0,'confidence':.99,'probabilities':{'0':1,'1':0,'2':0}}
    return {'answers':answers}

def test_score_scale_cannot_be_chosen_by_response():
    body=_scalar_response()
    body['answers']['judge_score']={'score':2,'confidence':.99,'probabilities':{'0':0,'100':1}}
    with pytest.raises(ValueError,match='scale|probabilities'):
        parse_jev_answers(body,_bundle())

def test_all_scalar_questions_require_confidence():
    body=_scalar_response()
    del body['answers']['q6_safety_gate']['confidence']
    with pytest.raises(ValueError,match='confidence'):
        parse_jev_answers(body,_bundle())


def test_q7_confidence_is_distinct_from_lowest_question_confidence():
    body = _scalar_response()
    body["answers"]["q2_fact_support"]["confidence"] = 0.12
    body["answers"]["q7_final_decision"]["confidence"] = 0.88
    parsed = parse_jev_answers(body, _bundle())
    assert parsed["decision"] == "expose"
    assert parsed["decision_confidence"] == 0.88
    assert parsed["confidence"] == 0.12


def test_escalated_field_only_describes_model_disposition():
    body = _scalar_response()
    body["answers"]["q7_final_decision"].update(choice="human_review", escalated=False)
    parsed = parse_jev_answers(body, _bundle())
    assert parsed["decision"] == "human_review"
    assert parsed["escalated"] is True

@pytest.mark.parametrize('section,key,value', [
    ('disclosure','flag',{'impressions':99}),
    ('item','functions',[{'gold_decision':'expose'}]),
    ('scene','tags',[{'impressions':99}]),
    ('coverage','complete',{'gold_decision':'expose'}),
    ('rule_features','price_mismatch',{'gold_decision':'expose'}),
])
def test_nested_untyped_data_is_rejected(section,key,value):
    payload=build_jev_input(_bundle())
    payload['facts'][section][key]=value
    with pytest.raises(ValueError):
        validate_jev_input(payload)

def test_mixed_archive_and_scalar_response_is_rejected():
    body=_scalar_response()
    body['answers']['q7_final_decision'].update(score=0,risk_type='compliant')
    body['answers']['risk_type']['choice']='price_misleading'
    with pytest.raises(ValueError,match='mixed|format'):
        parse_jev_answers(body,_bundle())

def test_high_risk_probabilities_cannot_claim_zero_score():
    body=_scalar_response()
    body['answers']['judge_score']['probabilities']={'0':0,'1':0,'2':1}
    assert parse_jev_answers(body,_bundle())['judge_score']==1

def test_live_protocol_rejects_archived_three_question_response():
    old={'answers':{'decision':{'choice':'expose','confidence':.9},
                    'risk_type':{'choice':'compliant','confidence':.9},'judge_score':{'score':0}}}
    with pytest.raises(ValueError,match='format'):
        parse_jev_answers(old,_bundle(), expected_protocol='jev-questions-v1')


def test_q2_experiment_changes_only_q2_and_preserves_legacy_protocol():
    import hashlib
    import json

    old = build_jev_questions('jev-questions-v1')
    current = build_jev_questions('jev-questions-v2')
    control = build_jev_questions('jev-questions-v2-q2-legacy')
    assert len(current) == 9
    assert sum(q['type'] == 'choice' for q in current.values()) == 8
    assert {key for key in current if current[key] != control[key]} == {'q2_fact_support'}
    assert control['q2_fact_support'] == old['q2_fact_support']
    # A frozen hash verifies all nine v1 questions, not only the Q2 used in A/B.
    digest = hashlib.sha256(json.dumps(old, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode()).hexdigest()
    assert digest == 'b496ce9fbd13a0ed600b05e6bc8cb15da813e8420d6705a2fac943bdabba2d5d'


@pytest.mark.parametrize('version', ['jev-questions-v1', 'jev-questions-v2', 'jev-questions-v2-q2-legacy'])
def test_input_and_response_use_the_requested_question_version(version):
    payload = build_jev_input(_bundle(), question_version=version)
    assert payload['question_schema_version'] == version
    assert payload['questions'] == build_jev_questions(version)
    parsed = parse_jev_answers(_scalar_response(), _bundle(), expected_protocol=version)
    assert parsed['protocol_completeness'] == version
    assert parsed['question_confidences']['q2_fact_support'] == .99
    assert parsed['question_choices']['q2_fact_support'] == 'supported'


def test_declared_question_version_cannot_hide_different_question_definitions():
    payload = build_jev_input(_bundle(), question_version='jev-questions-v2')
    payload['questions'] = build_jev_questions('jev-questions-v2-q2-legacy')
    with pytest.raises(ValueError, match='questions schema'):
        validate_jev_input(payload)
    with pytest.raises(ValueError, match='question schema version'):
        build_jev_questions('jev-questions-unknown')


@pytest.mark.parametrize('status,flag', [('visible', True), ('missing', False), ('unknown', None)])
def test_disclosure_status_preserves_an_independent_known_or_unknown_state(status, flag):
    bundle = _bundle()
    bundle['disclosure'] = {'flag': flag, 'required': True, 'status': status}
    payload = build_jev_input(bundle)
    assert payload['facts']['disclosure']['status'] == status
    assert payload['facts']['verification_state'] == 'verified'


@pytest.mark.parametrize('status,flag', [('visible', None), ('unknown', True), ('missing', True), ('invalid', None)])
def test_disclosure_status_cannot_conflict_with_the_actual_flag(status, flag):
    bundle = _bundle()
    bundle['disclosure'] = {'flag': flag, 'required': True, 'status': status}
    with pytest.raises(ValueError, match='disclosure'):
        build_jev_input(bundle)


def test_unknown_question_version_cannot_disable_strict_live_response_validation():
    with pytest.raises(ValueError, match='question schema version'):
        parse_jev_answers(_scalar_response(), _bundle(), expected_protocol='unrecognized')


@pytest.mark.parametrize('version', ['jev-questions-v1', 'jev-questions-v2', 'jev-questions-v2-q2-legacy'])
def test_archived_q7_format_cannot_masquerade_as_a_requested_scalar_protocol(version):
    response = _scalar_response()
    response['answers'].pop('risk_type')
    response['answers'].pop('judge_score')
    response['answers']['q7_final_decision'].update(
        risk_type='compliant', score=.1, evidence=['items.functions'])
    parsed = parse_jev_answers(response, _bundle())
    assert parsed['protocol_completeness'] == 'jev-questions-v1'
    assert parsed['judge_score'] == .1
    with pytest.raises(ValueError, match='scalar protocol'):
        parse_jev_answers(response, _bundle(), expected_protocol=version)
