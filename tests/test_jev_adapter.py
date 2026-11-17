import json

import pytest

from jev_adapter import JevAdapter, JevConfigurationError, validate_decision


def test_build_payload_uses_systemone_contract():
    adapter = JevAdapter(api_key="test-key", dry_run=True)
    bundle = {"reason_id": "r1", "generated_reason": "折叠收纳", "verification_state": "verified"}

    payload = adapter.build_payload(bundle)

    assert payload["model"] == "jev-1.14.0"
    assert "r1" in payload["state"]
    assert set(payload["questions"]) == {"decision", "risk_type", "judge_score"}
    assert payload["questions"]["decision"]["type"] == "choice"


def test_dry_run_does_not_make_a_network_call():
    adapter = JevAdapter(api_key="test-key", dry_run=True)
    result = adapter.judge({"reason_id": "r1", "generated_reason": "折叠收纳"})

    assert result["dry_run"] is True
    assert result["request"]["model"] == "jev-1.14.0"
    assert "questions" in result["request"]


def test_live_call_requires_api_key():
    adapter = JevAdapter(api_key=None, dry_run=False)

    with pytest.raises(JevConfigurationError):
        adapter.judge({"reason_id": "r1"})


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


def test_unverifiable_bundle_is_forced_to_human_review():
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

    assert result["decision"] == "human_review"
    assert result["escalated"] is True


def test_missing_disclosure_cannot_directly_expose():
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

    assert result["decision"] == "rewrite"
    assert result["risk_type"] == "missing_ai_disclosure"


def test_unverifiable_state_takes_precedence_over_missing_disclosure():
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

    assert result["decision"] == "human_review"
    assert result["escalated"] is True


def test_absolute_claim_block_is_downgraded_to_rewrite_when_mechanically_fixable():
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

    assert result["decision"] == "rewrite"
    assert result["risk_type"] == "absolute_claim"


def test_off_topic_block_is_downgraded_to_rewrite_when_verified():
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

    assert result["decision"] == "rewrite"
    assert result["risk_type"] == "off_topic"


def test_unsupported_efficacy_takes_risk_type_priority_over_absolute_claim():
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
    assert result["risk_type"] == "efficacy_or_medical_claim"


def test_supported_efficacy_prevents_false_positive_blocking():
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

    assert result["decision"] == "expose"
    assert result["risk_type"] == "compliant"


def test_verified_candidate_without_rule_signals_is_forced_to_expose():
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

    assert result["decision"] == "expose"
    assert result["risk_type"] == "compliant"
