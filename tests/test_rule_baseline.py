import pytest

from run_rule_baseline import evaluate_candidate


def base_candidate(reason: str, **overrides):
    candidate = {
        "reason_id": "r_test",
        "generated_reason": reason,
        "user_context": {"city": "杭州", "recent_categories": ["家居日用"]},
        "item_attrs_returned": {
            "title": "折叠收纳盒",
            "category": "家居日用",
            "subcategory": "收纳整理",
            "functions": ["折叠", "防尘", "分区收纳"],
            "suitable_scenes": ["卧室整理"],
            "target_tags": ["收纳"],
            "price": 39.9,
            "promo_ids": [],
        },
        "attrs_returned_complete": True,
        "promo_computed_in_code": {},
        "ai_disclosure_flag_from_code": True,
        "tool_trace": [
            {"tool": "get_item", "returned_fields": ["functions", "suitable_scenes"]}
        ],
    }
    candidate.update(overrides)
    return candidate


LEXICON = [
    {"term": "防潮", "risk_type": "efficacy_or_medical_claim", "severity": "high", "canonical_term": "防潮"},
    {"term": "除湿", "risk_type": "efficacy_or_medical_claim", "severity": "high", "canonical_term": "除湿"},
    {"term": "全网最低价", "risk_type": "absolute_claim", "severity": "high", "canonical_term": "全网最低价"},
    {"term": "满99减50", "risk_type": "price_misleading", "severity": "high", "canonical_term": "满99减50"},
]


def test_unsupported_efficacy_claim_is_blocked():
    result = evaluate_candidate(base_candidate("梅雨季防潮神器"), LEXICON)

    assert result["decision"] == "block"
    assert result["risk_type"] == "efficacy_or_medical_claim"
    assert result["judge_score"] >= 0.9
    assert result["evidence"]
    assert result["escalated"] is False


def test_missing_attributes_routes_to_human_review():
    candidate = base_candidate(
        "梅雨季防潮神器",
        attrs_returned_complete=False,
        item_attrs_returned={"category": "家居日用", "price": 39.9},
        tool_trace=[{"tool": "get_item", "returned_fields": ["category", "price"]}],
    )
    result = evaluate_candidate(candidate, LEXICON)

    assert result["decision"] == "human_review"
    assert result["escalated"] is True
    assert "字段" in " ".join(result["evidence"])


def test_missing_ai_disclosure_is_rewrite():
    result = evaluate_candidate(
        base_candidate("卧室整理更方便", ai_disclosure_flag_from_code=False), LEXICON
    )

    assert result["decision"] == "rewrite"
    assert result["risk_type"] == "missing_ai_disclosure"
    assert result["evidence"]


def test_supported_reason_is_exposed():
    result = evaluate_candidate(base_candidate("折叠收纳，卧室整理更方便"), LEXICON)

    assert result["decision"] == "expose"
    assert result["risk_type"] == "compliant"
    assert 0 <= result["judge_score"] < 0.2
    assert result["evidence"]


def test_price_mismatch_is_blocked():
    candidate = base_candidate(
        "满99减50",
        promo_computed_in_code={
            "promo_id": "promo_test",
            "type": "full_reduction",
            "threshold_cents": 9900,
            "discount_cents": 1000,
            "applicable": True,
        },
    )
    result = evaluate_candidate(candidate, LEXICON)

    assert result["decision"] == "block"
    assert result["risk_type"] == "price_misleading"
    assert result["evidence"]


def test_project_lexicon_covers_pilot_claim_variants():
    from run_rule_baseline import load_lexicon

    terms = {entry["term"] for entry in load_lexicon("compliance_lexicon.txt")}
    assert "最便宜" in terms
    assert "改善失眠" in terms
