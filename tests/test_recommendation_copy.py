import json

import pytest

from recommendation_copy import build_copy_brief, copy_generation_instructions, validate_reason_text


def test_brief_separates_product_facts_from_relevance_and_excludes_behavior():
    context = {
        "item": {"title": "抽纸", "spec": "24包", "functions": ["清洁", "吸水"],
                 "material": "原生木浆", "price_cents": 2990, "rating": 4.9,
                 "sales_30d": 999, "qualifications": ["无"], "unknown": "卖点"},
        "user_context": {"city": "广州", "life_stage": "新手妈妈", "tags": ["有娃"],
                         "preferred_categories": ["家居日用"], "last_search_terms": ["秘密搜索"],
                         "recent_cart_item_ids": ["i_0123"], "ctr": 0.5,
                         "events": [{"clicked": True}]},
        "gold": "标签", "exposure_reason": "旧文案", "promo": {"title": "优惠"},
    }
    brief = build_copy_brief(context)
    assert brief["product_facts"]["items.material"] == "原生木浆"
    assert brief["scene_facts"]["users.life_stage"] == "新手妈妈"
    assert brief["relevance_hints"]["users.preferred_categories"] == ["家居日用"]
    assert "users.preferred_categories" not in brief["evidence_allowlist"]
    assert "items.spec" not in brief["product_facts"]
    assert "items.spec" not in brief["evidence_allowlist"]
    serialized = json.dumps(brief, ensure_ascii=False)
    for excluded in ("秘密搜索", "i_0123", "旧文案", '"rating"', '"sales_30d"', '"ctr"', '"gold"', '"price_cents"'):
        assert excluded not in serialized
    assert "不证明特定用户当前家庭" in serialized


def test_missing_product_fields_never_become_available_evidence():
    brief = build_copy_brief({"item_attrs_returned": {"title": "抽纸", "functions": [], "spec": None}, "user_context": {"city": ""}})
    assert brief["product_facts"] == {"items.title": "抽纸"}
    assert brief["evidence_allowlist"] == ["items.title"]
    assert "柔软" not in brief["product_facts"].values()


def test_brief_does_not_mutate_nested_source_values():
    context = {"item": {"functions": ["清洁"]}}
    brief = build_copy_brief(context)
    brief["product_facts"]["items.functions"].append("添加")
    assert context["item"]["functions"] == ["清洁"]


def test_brief_uses_supplied_scenario_date_without_inventing_weather():
    brief = build_copy_brief({"item": {"title": "身体乳"}, "time_context": {"scenario_date": "2026-06-15", "weather": "下雪"}})
    assert brief["scene_facts"] == {"time_context.scenario_date": "2026-06-15"}
    assert "time_context.scenario_date" in brief["evidence_allowlist"]
    assert "weather" not in json.dumps(brief)
    assert "time_context.scenario_date" not in build_copy_brief({"item": {}})["evidence_allowlist"]


def test_length_counts_all_unicode_characters_including_punctuation_and_emoji():
    reason = "纸" * 18 + "！✨"
    assert validate_reason_text(reason) == reason
    assert validate_reason_text("a" * 20) == "a" * 20
    with pytest.raises(ValueError, match="Unicode"):
        validate_reason_text("纸" * 19 + "！✨")
    with pytest.raises(ValueError, match="Unicode"):
        validate_reason_text("\U00020000" * 21)


@pytest.mark.parametrize("reason", [
    "24包抽纸", "三层抽纸", "三十四厘米炒锅", "二十四包装", "二十个收纳盒",
    "三米长桌布", "500ml水杯", "两公斤大米", "６８键键盘", "PBT键帽", "十倍清洁力",
    "兩包抽纸", "雙層抽纸", "單層抽纸", "单层抽纸", "十几包抽纸", "十幾包抽纸", "多件装抽纸",
])
def test_product_quantities_and_parameters_are_rejected(reason):
    with pytest.raises(ValueError, match="parameter"):
        validate_reason_text(reason)


@pytest.mark.parametrize("reason", ["正红一抹，哑光显色", "不粘少油烟，三餐有滋味", "原生木浆抽纸，清洁随手抽"])
def test_natural_numeral_phrases_remain_available(reason):
    assert validate_reason_text(reason) == reason


def test_creative_instruction_uses_total_character_limit_and_product_focus():
    instruction = copy_generation_instructions()
    assert instruction["length"]["max_unicode_characters"] == 20
    assert instruction["length"]["target_unicode_characters"] == [8, 18]
    assert "不靠截断长句" in json.dumps(instruction, ensure_ascii=False)


@pytest.mark.parametrize("value", [None, 123, [], "", "  ", " 短句", "短句 ", "短句\n下一句", "短句\r", "短句\t", "短句\u2028"])
def test_invalid_or_multiline_reason_is_rejected(value):
    with pytest.raises(ValueError):
        validate_reason_text(value)
