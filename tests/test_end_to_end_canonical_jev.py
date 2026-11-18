import json

from fact_bundle import build_fact_bundle
from generate_full_candidates import build_full_dataset
from jev_adapter import JevAdapter
from run_rule_baseline import load_lexicon


def test_canonical_candidate_fact_bundle_and_jev_request_keep_identity_and_block_feedback():
    candidates, _ = build_full_dataset(seed=20261116)
    candidate = candidates[0]
    bundle = build_fact_bundle(candidate, load_lexicon("data/raw/compliance_lexicon.txt"))
    result = JevAdapter(api_key="test-key", dry_run=True).judge(bundle)
    request = result["request"]
    state = json.loads(request["state"])

    assert state["candidate"]["reason_id"] == bundle["reason_id"]
    assert bundle["item_id"].startswith("i_")
    assert state["candidate"]["item_id"] == bundle["item_id"]
    assert state["trace"]["data_version"] == "canonical-2026-06-15-v1"
    assert state["question_schema_version"] == "jev-questions-v1"
    for forbidden in ("history", "ctr", "click", "order", "refund", "complaint", "sorting", "search", "cart"):
        assert forbidden not in json.dumps(state, ensure_ascii=False).lower()


def _bundle(state="verified", reason="普通推荐理由"):
    return {
        "reason_id": "r_route",
        "item_id": "i_0001",
        "generated_reason": reason,
        "verification_state": state,
        "coverage": {"missing": ["functions"]} if state == "unverifiable" else {"missing": []},
        "item": {"functions": ["折叠"]},
        "disclosure": {"flag": True, "required": True},
        "rule_features": {
            "unsupported_efficacy_terms": ["治疗"] if state == "verified" and "治疗" in reason else [],
            "supported_efficacy_terms": [],
            "absolute_claim_terms": ["最好"] if "最好" in reason else [],
            "price_mismatch": False,
            "topic_mismatch": False,
        },
        "lexicon_hits": [],
    }


def _old_response(decision, risk_type, score=0.9):
    return {
        "model": "jev-1.14.0",
        "answers": {
            "decision": {"choice": decision, "confidence": 0.95},
            "risk_type": {"choice": risk_type, "confidence": 0.95},
            "judge_score": {"score": score},
        },
    }


def test_hard_risk_unverifiable_and_rewriteable_routes_are_distinct():
    adapter = JevAdapter(api_key="test-key", dry_run=False)

    blocked = adapter.parse_response(
        _old_response("block", "efficacy_or_medical_claim"),
        _bundle(reason="治疗失眠的收纳盒"),
    )
    unverifiable = adapter.parse_response(
        _old_response("block", "efficacy_or_medical_claim"),
        _bundle(state="unverifiable", reason="梅雨季防潮推荐"),
    )
    rewriteable = adapter.parse_response(
        _old_response("rewrite", "absolute_claim"),
        _bundle(reason="最好用的收纳盒"),
    )

    assert blocked["decision"] == "block"
    assert unverifiable["decision"] == "human_review"
    assert rewriteable["decision"] == "rewrite"
