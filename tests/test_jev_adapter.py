import json

import pytest

from jev_adapter import JevAdapter, JevConfigurationError, validate_decision
from jev_protocol import JEV_QUESTION_SCHEMA_VERSION


def _payload_bundle():
    return {
        "schema_version": "fact-bundle-v2",
        "reason_id": "r1",
        "user_id": "u_0001",
        "item_id": "i_0001",
        "exposure_reason": "折叠收纳",
        "generated_reason": "折叠收纳",
        "evidence_fields": ["items.functions"],
        "user_context": {"city": "广州"},
        "item": {"item_id": "i_0001", "title": "收纳盒", "functions": ["折叠"]},
        "promo": {},
        "coverage": {"missing": [], "complete": True},
        "verification_state": "verified",
        "disclosure": {"flag": True, "required": True},
        "rule_features": {},
        "provenance": {"item": "data/raw/items.csv:item_id=i_0001"},
        "data_version": "canonical-2026-06-15-v1",
    }


def test_build_payload_uses_systemone_contract():
    adapter = JevAdapter(api_key="test-key", dry_run=True)
    bundle = _payload_bundle()

    payload = adapter.build_payload(bundle)

    assert payload["model"] == "jev-1.14.0"
    assert "r1" in payload["state"]
    assert set(payload) == {"model", "state", "questions"}
    assert json.loads(payload["state"])["question_schema_version"] == JEV_QUESTION_SCHEMA_VERSION
    assert set(payload["questions"]) == {
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
    assert payload["questions"]["q1_identity"]["type"] == "choice"


def test_dry_run_does_not_make_a_network_call():
    adapter = JevAdapter(api_key="test-key", dry_run=True)
    result = adapter.judge(_payload_bundle())

    assert result["dry_run"] is True
    assert result["request"]["model"] == "jev-1.14.0"
    assert "questions" in result["request"]


def test_live_call_requires_api_key():
    adapter = JevAdapter(api_key=None, dry_run=False)

    with pytest.raises(JevConfigurationError):
        adapter.judge({"reason_id": "r1"})


def test_response_observer_receives_body_before_parsing(monkeypatch):
    raw = '  {"server":"response"}\n'
    events = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return raw.encode("utf-8")

    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    adapter = JevAdapter(
        api_key="private-test-key", dry_run=False,
        response_observer=lambda reason_id, body: events.append(("response", reason_id, body)),
    )

    def parse_response(body, bundle, **kwargs):
        events.append(("parse", bundle["reason_id"], body))
        raise ValueError("test parser rejected response")

    monkeypatch.setattr(adapter, "parse_response", parse_response)
    with pytest.raises(ValueError, match="parser rejected"):
        adapter.judge(_payload_bundle())
    assert events == [("response", "r1", raw), ("parse", "r1", raw)]


def test_dry_run_never_notifies_response_observer(monkeypatch):
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_args, **_kwargs: pytest.fail("dry run called network"))
    adapter = JevAdapter(
        dry_run=True,
        response_observer=lambda *_: pytest.fail("dry run fabricated a response"),
    )
    assert adapter.judge(_payload_bundle())["dry_run"] is True


def test_validate_decision_rejects_empty_evidence():
    with pytest.raises(ValueError):
        validate_decision({
            "reason_id": "r1",
            "decision": "block",
            "risk_type": "absolute_claim",
            "evidence": [],
            "judge_score": 0.9,
            "escalated": False,
            "model_version": "jev-1.14.0",
            "score_name": "jev-compliance-v1",
        })


def test_parse_systemone_response_into_project_decision():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "expose", "confidence": 0.9},
            "risk_type": {"type": "choice", "choice": "compliant", "confidence": 0.95},
            "judge_score": {"type": "score", "score": 0.0, "probabilities": {"0": 1.0, "1": 0.0, "2": 0.0}},
        },
    }
    bundle = {
        "reason_id": "r1",
        "verification_state": "verified",
        "item": {"functions": ["折叠"]},
        "coverage": {"missing": []},
        "disclosure": {"flag": True},
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "expose"
    assert result["risk_type"] == "compliant"
    assert result["judge_score"] == 0.0
    assert result["model_version"] == "jev-1.14.0"
    assert result["score_name"] == "jev-compliance-v1"
    assert result["evidence"]


def test_ssl_context_keeps_verification_enabled():
    from jev_adapter import build_ssl_context
    import ssl

    context = build_ssl_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_unverifiable_bundle_preserves_model_block():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "block", "confidence": 0.95},
            "risk_type": {"type": "choice", "choice": "efficacy_or_medical_claim", "confidence": 0.95},
            "judge_score": {"type": "score", "score": 2, "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0}},
        },
    }
    bundle = {
        "reason_id": "r_missing",
        "verification_state": "unverifiable",
        "coverage": {"missing": ["functions"]},
        "item": {},
        "disclosure": {"flag": True},
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "block"
    assert result["escalated"] is False


def test_disclosure_configuration_preserves_model_expose():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "expose", "confidence": 0.95},
            "risk_type": {"type": "choice", "choice": "compliant", "confidence": 0.95},
            "judge_score": {"type": "score", "score": 0, "probabilities": {"0": 1.0, "1": 0.0, "2": 0.0}},
        },
    }
    bundle = {
        "reason_id": "r_disclosure",
        "verification_state": "verified",
        "coverage": {"missing": []},
        "item": {"functions": ["折叠"]},
        "disclosure": {"flag": False},
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "expose"
    assert result["risk_type"] == "compliant"
    assert result["configuration_notes"] == ["ai_disclosure_missing"]


def test_unverifiable_facts_preserve_model_rewrite():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "rewrite", "confidence": 0.9},
            "risk_type": {"type": "choice", "choice": "missing_ai_disclosure", "confidence": 0.9},
            "judge_score": {"type": "score", "score": 2, "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0}},
        },
    }
    bundle = {
        "reason_id": "r_missing_disclosure",
        "verification_state": "unverifiable",
        "coverage": {"missing": ["functions"]},
        "item": {},
        "disclosure": {"flag": False},
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "rewrite"
    assert result["escalated"] is False


def test_absolute_claim_model_block_is_preserved():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "block", "confidence": 0.95},
            "risk_type": {"type": "choice", "choice": "absolute_claim", "confidence": 0.95},
            "judge_score": {"type": "score", "score": 2, "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0}},
        },
    }
    bundle = {
        "reason_id": "r_absolute",
        "verification_state": "verified",
        "coverage": {"missing": []},
        "item": {"functions": ["折叠"]},
        "lexicon_hits": [{"term": "全网最低价", "canonical_term": "全网最低价", "risk_type": "absolute_claim", "severity": "high"}],
        "disclosure": {"flag": True},
        "rule_features": {"unsupported_efficacy_terms": []},
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "block"
    assert result["risk_type"] == "absolute_claim"


def test_off_topic_model_block_is_preserved():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "block", "confidence": 0.95},
            "risk_type": {"type": "choice", "choice": "off_topic", "confidence": 0.95},
            "judge_score": {"type": "score", "score": 1, "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0}},
        },
    }
    bundle = {
        "reason_id": "r_topic",
        "verification_state": "verified",
        "coverage": {"missing": []},
        "item": {"category": "家居日用", "functions": ["折叠"]},
        "lexicon_hits": [],
        "disclosure": {"flag": True},
        "rule_features": {"unsupported_efficacy_terms": []},
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "block"
    assert result["risk_type"] == "off_topic"


def test_rule_features_preserve_model_risk_type():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "block", "confidence": 0.95},
            "risk_type": {"type": "choice", "choice": "absolute_claim", "confidence": 0.95},
            "judge_score": {"type": "score", "score": 2, "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0}},
        },
    }
    bundle = {
        "reason_id": "r_efficacy",
        "verification_state": "verified",
        "coverage": {"missing": []},
        "item": {"functions": ["折叠"]},
        "lexicon_hits": [],
        "disclosure": {"flag": True},
        "rule_features": {"unsupported_efficacy_terms": ["除湿"]},
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "block"
    assert result["risk_type"] == "absolute_claim"


def test_supported_efficacy_does_not_override_model_rewrite():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "rewrite", "confidence": 0.8},
            "risk_type": {"type": "choice", "choice": "efficacy_or_medical_claim", "confidence": 0.8},
            "judge_score": {"type": "score", "score": 1, "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0}},
        },
    }
    bundle = {
        "reason_id": "r_supported_efficacy",
        "verification_state": "verified",
        "coverage": {"missing": []},
        "item": {"functions": ["除湿"]},
        "lexicon_hits": [{"term": "除湿", "canonical_term": "除湿", "risk_type": "efficacy_or_medical_claim", "severity": "high"}],
        "disclosure": {"flag": True},
        "rule_features": {"unsupported_efficacy_terms": [], "supported_efficacy_terms": ["除湿"]},
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "rewrite"
    assert result["risk_type"] == "efficacy_or_medical_claim"


def test_verified_candidate_without_rule_signals_preserves_model_block():
    adapter = JevAdapter(api_key="test-key", dry_run=False)
    body = {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"type": "choice", "choice": "block", "confidence": 0.7},
            "risk_type": {"type": "choice", "choice": "compliant", "confidence": 0.7},
            "judge_score": {"type": "score", "score": 1, "probabilities": {"0": 0.2, "1": 0.8, "2": 0.0}},
        },
    }
    bundle = {
        "reason_id": "r_clean",
        "verification_state": "verified",
        "coverage": {"missing": []},
        "item": {"functions": ["折叠"], "suitable_scenes": ["卧室整理"]},
        "lexicon_hits": [],
        "disclosure": {"flag": True, "required": True},
        "rule_features": {
            "unsupported_efficacy_terms": [],
            "supported_efficacy_terms": [],
            "absolute_claim_terms": [],
            "price_mismatch": False,
            "topic_mismatch": False,
        },
    }

    result = adapter.parse_response(body, bundle)

    assert result["decision"] == "block"
    assert result["risk_type"] == "compliant"

def _response(decision='expose', confidence=.95):
    return {'answers': {'decision': {'choice': decision, 'confidence': confidence}, 'risk_type': {'choice': 'compliant', 'confidence': confidence}, 'judge_score': {'score': 0}}}

def test_low_confidence_is_recorded_with_model_expose():
    bundle = _payload_bundle()
    result = JevAdapter().parse_response(_response(confidence=.4), bundle)
    assert result['decision'] == 'expose'
    assert result['confidence'] == .4
    assert result['escalated'] is False

def test_clean_rules_do_not_override_model_block():
    bundle = _payload_bundle()
    bundle['rule_features'] = {'absolute_claim_terms': [], 'price_mismatch': False, 'topic_mismatch': False, 'unsupported_efficacy_terms': []}
    assert JevAdapter().parse_response(_response('block'), bundle)['decision'] == 'block'

def test_raw_object_preserves_model_decision_for_unverifiable_facts():
    bundle = _payload_bundle()
    bundle['verification_state'] = 'unverifiable'
    body = {'reason_id':'r1','decision':'expose','risk_type':'compliant','judge_score':0,'evidence':['items.functions'],'escalated':False}
    assert JevAdapter().parse_response(body, bundle)['decision'] == 'expose'

def test_legacy_score_is_normalized_from_probabilities_scale():
    body = _response()
    body['answers']['judge_score'] = {'score':1, 'probabilities': {'0':0,'1':1,'2':0}}
    assert JevAdapter().parse_response(body, _payload_bundle())['judge_score'] == .5

def test_nonfinite_score_rejected():
    from jev_adapter import JevResponseError
    body = _response()
    body['answers']['judge_score']['score'] = float('nan')
    with pytest.raises(JevResponseError):
        JevAdapter().parse_response(body, _payload_bundle())

def test_q7_expose_is_returned_alongside_q6_human_review():
    from jev_protocol import build_jev_questions
    answers = {key:{'choice':next(iter(q['criteria'])), 'confidence':.96}
               for key,q in build_jev_questions().items() if q['type']=='choice'}
    answers['q6_safety_gate']['choice']='human_review'
    answers['judge_score']={'score':0,'confidence':.96,'probabilities':{'0':1,'1':0,'2':0}}
    result=JevAdapter().parse_response({'answers':answers},_payload_bundle())
    assert result['decision']=='expose'
    assert result['safety_gate_choice']=='human_review'

def test_model_version_is_consistent_across_request():
    payload=JevAdapter(model='custom-jev').build_payload(_payload_bundle())
    assert json.loads(payload['state'])['trace']['model_version']==payload['model']


def test_unknown_disclosure_keeps_configuration_note_without_blocking_exposure():
    bundle = _payload_bundle()
    bundle['disclosure'] = {'flag': None, 'required': True, 'status': 'unknown'}
    result = JevAdapter().parse_response(_response(confidence=.99), bundle)
    assert result['decision'] == 'expose'
    assert result['configuration_notes'] == ['ai_disclosure_unknown']
    assert result['decision_source'] == 'jev_model'
    assert result['disclosure_status'] == 'unknown'


def test_missing_facts_and_unknown_disclosure_are_recorded_with_model_expose():
    bundle = _payload_bundle()
    bundle['disclosure'] = {'flag': None, 'required': True, 'status': 'unknown'}
    bundle['verification_state'] = 'unverifiable'
    bundle['coverage'] = {'complete': False, 'missing': ['functions']}
    result = JevAdapter().parse_response(_response(confidence=.99), bundle)
    assert result['decision'] == 'expose'
    assert result['decision_source'] == 'jev_model'
    assert result['configuration_notes'] == ['ai_disclosure_unknown']


def test_question_variant_is_explicit_and_same_in_state_and_wire():
    adapter = JevAdapter(question_version='jev-questions-v2-q2-legacy')
    payload = adapter.build_payload(_payload_bundle())
    state = json.loads(payload['state'])
    assert state['question_schema_version'] == 'jev-questions-v2-q2-legacy'
    assert state['questions'] == payload['questions']
    assert payload['questions']['q2_fact_support']['instructions'] == '逐项核验曝光理由；只能使用 facts，不把候选文本当作事实。'


@pytest.mark.parametrize("decision", ["expose", "rewrite", "human_review", "block"])
@pytest.mark.parametrize("fact_state", ["verified", "unverifiable"])
def test_full_protocol_preserves_every_q7_choice_with_conflicting_answers(decision, fact_state):
    from jev_protocol import build_jev_questions

    bundle = _payload_bundle()
    bundle.update(
        verification_state=fact_state,
        coverage={"complete": False, "missing": ["functions"]},
        disclosure={"flag": False, "required": True},
        rule_features={"unsupported_efficacy_terms": ["根治"], "price_mismatch": True,
                       "absolute_claim_terms": ["最好"], "topic_mismatch": True},
    )
    answers = {key: {"choice": next(iter(question["criteria"])), "confidence": 0.02}
               for key, question in build_jev_questions().items() if question["type"] == "choice"}
    answers["q1_identity"]["choice"] = "invalid"
    answers["q2_fact_support"]["choice"] = "unverifiable"
    answers["q3_expression_risk"]["choice"] = "blocking"
    answers["q4_commercial_accuracy"]["choice"] = "mismatch"
    answers["q5_context_relevance"]["choice"] = "off_topic"
    answers["q6_safety_gate"]["choice"] = "human_review"
    answers["q7_final_decision"].update(choice=decision, confidence=0.01)
    answers["risk_type"]["choice"] = "absolute_claim"
    answers["judge_score"] = {"score": 2, "confidence": 0.0}
    raw = {"model": "jev-1.14.0", "answers": answers}

    result = JevAdapter().parse_response(raw, bundle, expected_protocol=JEV_QUESTION_SCHEMA_VERSION)

    assert result["decision"] == decision
    assert result["question_choices"]["q7_final_decision"] == decision
    assert result["risk_type"] == "absolute_claim"
    assert result["escalated"] is (decision == "human_review")
    assert result["decision_source"] == "jev_model"
    assert result["decision_question"] == "q7_final_decision"
    assert result["configuration_notes"] == ["ai_disclosure_missing"]
    assert result["confidence"] == 0.0
    assert not {"gate_reasons", "confidence_threshold", "policy_version"}.intersection(result)
    assert raw["answers"]["q7_final_decision"]["choice"] == decision


def test_incomplete_protocol_raises_error_without_manufacturing_a_disposition():
    from jev_adapter import JevResponseError

    with pytest.raises(JevResponseError, match="valid Jev question answer"):
        JevAdapter().parse_response(
            {"answers": {"q7_final_decision": {"choice": "expose", "confidence": 0.1}}},
            _payload_bundle(), expected_protocol=JEV_QUESTION_SCHEMA_VERSION,
        )


def test_raw_model_version_mismatch_is_rejected():
    from jev_adapter import JevResponseError

    body = {"reason_id": "r1", "decision": "expose", "risk_type": "compliant", "judge_score": 0,
            "evidence": ["items.functions"], "escalated": False, "model_version": "another-model"}
    with pytest.raises(JevResponseError, match="response model"):
        JevAdapter().parse_response(body, _payload_bundle())


def _complete_response():
    from jev_protocol import build_jev_questions

    answers = {key: {"choice": next(iter(question["criteria"])), "confidence": 0.1}
               for key, question in build_jev_questions().items() if question["type"] == "choice"}
    answers["q4_commercial_accuracy"]["choice"] = "not_mentioned"
    answers["judge_score"] = {"score": 0, "confidence": 0.1}
    return {"model": "jev-1.14.0", "answers": answers}


@pytest.mark.parametrize("as_bytes", [False, True])
@pytest.mark.parametrize("duplicate", [
    '"model":"another-model","model":"jev-1.14.0"',
    '"answers":{"q7_final_decision":{"choice":"block","choice":"expose","confidence":0.1}}',
])
def test_strict_response_json_rejects_duplicate_keys(as_bytes, duplicate):
    from jev_adapter import JevResponseError

    text = "{" + duplicate + "}"
    raw = text.encode("utf-8") if as_bytes else text
    with pytest.raises(JevResponseError, match="duplicate JSON key"):
        JevAdapter().parse_response(raw, _payload_bundle())


@pytest.mark.parametrize("as_bytes", [False, True])
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_strict_response_json_rejects_nonfinite_constants_even_in_unused_fields(as_bytes, constant):
    from jev_adapter import JevResponseError

    text = json.dumps(_complete_response())[:-1] + ',"unused":' + constant + '}'
    raw = text.encode("utf-8") if as_bytes else text
    with pytest.raises(JevResponseError, match="invalid JSON constant"):
        JevAdapter().parse_response(raw, _payload_bundle(), expected_protocol=JEV_QUESTION_SCHEMA_VERSION)


@pytest.mark.parametrize("field, invalid", [
    ("reason_id", "r_other"), ("item_id", "i_9999"),
    ("question_schema_version", "jev-questions-v1"),
    ("reason_id", None), ("item_id", None), ("question_schema_version", None),
])
def test_explicit_response_metadata_must_match_the_request(field, invalid):
    from jev_adapter import JevResponseError

    raw = _complete_response()
    raw[field] = invalid
    with pytest.raises(JevResponseError, match=f"response {field} mismatch"):
        JevAdapter().parse_response(raw, _payload_bundle(), expected_protocol=JEV_QUESTION_SCHEMA_VERSION)


@pytest.mark.parametrize("with_metadata", [False, True])
def test_official_response_with_optional_matching_metadata_keeps_q7(with_metadata):
    raw = _complete_response()
    if with_metadata:
        raw.update(reason_id="r1", item_id="i_0001", question_schema_version=JEV_QUESTION_SCHEMA_VERSION)

    result = JevAdapter().parse_response(json.dumps(raw), _payload_bundle(), expected_protocol=JEV_QUESTION_SCHEMA_VERSION)

    assert result["decision"] == raw["answers"]["q7_final_decision"]["choice"]
    assert result["decision_source"] == "jev_model"


def test_explicit_response_question_version_matches_the_requested_variant():
    requested_version = "jev-questions-v2-q2-legacy"
    raw = _complete_response()
    raw["question_schema_version"] = requested_version

    result = JevAdapter(question_version=requested_version).parse_response(
        raw, _payload_bundle(), expected_protocol=requested_version,
    )

    assert result["protocol_completeness"] == requested_version
    assert result["decision"] == raw["answers"]["q7_final_decision"]["choice"]
