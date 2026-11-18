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


def test_canonical_categories_and_audiences_are_topic_evidence():
    candidate = base_candidate("宝宝用的婴儿湿巾", item_attrs_returned={
        "item_id": "i_0131", "category_l1": "母婴亲子", "category_l3": "婴儿湿巾",
        "suit_audience": "婴幼儿", "functions": ["清洁"], "price_cents": 5990,
    })
    result = evaluate_candidate(candidate, LEXICON)
    assert result["decision"] == "expose"
    assert "functions" in " ".join(result["evidence"])


def test_product_title_cannot_prove_unsupported_efficacy():
    candidate = base_candidate("治疗鼻炎", item_attrs_returned={
        "item_id": "i_0001", "title": "治疗鼻炎神器", "functions": ["收纳"],
        "efficacy_claims_allowed": [], "category_l1": "家居日用",
    })
    lexicon = [{"term": "治疗", "risk_type": "efficacy_or_medical_claim", "severity": "critical", "canonical_term": "治疗"}]
    assert evaluate_candidate(candidate, lexicon)["decision"] == "block"


@pytest.mark.parametrize("overrides", [
    {"applicable": False}, {"start": "2026-05-01", "end": "2026-05-31"},
    {"scope": {"category_l1": ["3C数码"]}},
])
def test_promo_matching_amounts_still_require_valid_time_and_scope(overrides):
    promo = {"type": "full_reduction", "threshold_cents": 9900, "discount_cents": 1000,
             "applicable": True, "start": "2026-06-01", "end": "2026-06-30",
             "scope": {"category_l1": ["家居日用"]}}
    promo.update(overrides)
    candidate = base_candidate("满99减10", promo_computed_in_code=promo, snapshot_at="2026-06-15T08:00:00+08:00",
                               item_attrs_returned={"category_l1": "家居日用", "price_cents": 5990})
    assert evaluate_candidate(candidate, LEXICON)["decision"] == "block"


def test_canonical_price_cents_supports_literal_yuan_price_without_promo():
    candidate = base_candidate("仅需59.90元", item_attrs_returned={"price_cents": 5990})
    lexicon = [{"term": "仅需", "risk_type": "price_misleading", "severity": "medium", "canonical_term": "仅需"}]
    assert evaluate_candidate(candidate, lexicon)["decision"] == "expose"
    candidate["generated_reason"] = "仅需39.90元"
    assert evaluate_candidate(candidate, lexicon)["decision"] == "block"


def test_supported_mother_identity_does_not_require_baby_product():
    from canonical_data import load_canonical_items, load_canonical_users
    candidate = base_candidate(
        "新手妈妈也别忘了自己，正红一涂就显色",
        user_context=load_canonical_users()["u_0001"],
        item_attrs_returned=load_canonical_items()["i_0037"],
    )
    result = evaluate_candidate(candidate, LEXICON)
    assert result["decision"] == "expose"
    assert result["risk_type"] == "compliant"


@pytest.mark.parametrize("reason", [
    "新手妈妈也能用的婴儿专用口红",
    "宝宝用的正红口红，显色更轻松",
    "母婴专用口红，正红一涂就显色",
])
def test_user_mother_identity_cannot_prove_infant_product_suitability(reason):
    from canonical_data import load_canonical_items, load_canonical_users
    candidate = base_candidate(
        reason,
        user_context=load_canonical_users()["u_0001"],
        item_attrs_returned=load_canonical_items()["i_0037"],
    )
    result = evaluate_candidate(candidate, LEXICON)
    assert result["decision"] == "rewrite"
    assert result["risk_type"] == "off_topic"


def test_parent_scene_does_not_require_infant_product():
    from canonical_data import load_canonical_items
    candidate = base_candidate(
        "宝宝睡了，正红口红也留一点时间给自己",
        user_context={"life_stage": "新手妈妈", "tags": ["有娃", "宝妈"]},
        item_attrs_returned=load_canonical_items()["i_0037"],
    )
    assert evaluate_candidate(candidate, LEXICON)["decision"] == "expose"


def test_pet_product_mismatch_is_preserved_with_parent_identity():
    from canonical_data import load_canonical_items
    candidate = base_candidate(
        "新手妈妈给猫咪的宠物玩具",
        user_context={"life_stage": "新手妈妈", "tags": ["有娃"]},
        item_attrs_returned=load_canonical_items()["i_0037"],
    )
    result = evaluate_candidate(candidate, LEXICON)
    assert result["decision"] == "rewrite"
    assert result["risk_type"] == "off_topic"
