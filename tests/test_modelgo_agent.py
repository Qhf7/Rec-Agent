import json

import pytest

from modelgo_agent import AgentResponseError, ModelGoAgent, parse_agent_cards


def test_parse_agent_cards_validates_json_array_and_ids():
    raw = '{"cards":[{"user_id":"u1","item_id":"i1","generated_reason":"成都书房低噪除湿","evidence_fields":["city","functions"]}]}'
    cards = parse_agent_cards(raw, {"u1": "i1"})

    assert cards[0]["user_id"] == "u1"
    assert cards[0]["item_id"] == "i1"
    assert len(cards[0]["generated_reason"]) <= 20


def test_parse_agent_cards_accepts_user_facing_exposure_reason():
    raw = '{"cards":[{"user_id":"u1","item_id":"i1","exposure_reason":"通勤大容量更好装","evidence_fields":["city","functions"]}]}'
    cards = parse_agent_cards(raw, {"u1": "i1"})

    assert cards[0]["exposure_reason"] == "通勤大容量更好装"
    assert cards[0]["generated_reason"] == cards[0]["exposure_reason"]


def test_build_payload_requires_structured_output():
    agent = ModelGoAgent(api_key="test-key", dry_run=True)
    payload = agent.build_payload([
        {"user_id": "u1", "item_id": "i1", "user_context": {"city": "成都"}, "item": {"functions": ["折叠"]}}
    ])

    assert payload["model"] == "deepseek-v4-flash"
    assert "cards" in payload["messages"][1]["content"]
    assert "不超过20字符" in payload["messages"][1]["content"]
    assert payload["temperature"] == 0.7


def test_dry_run_returns_request_without_network():
    agent = ModelGoAgent(api_key="test-key", dry_run=True)
    result = agent.generate_batch([{"user_id": "u1", "item_id": "i1", "user_context": {}, "item": {}}])

    assert result["dry_run"] is True
    assert result["request"]["model"] == "deepseek-v4-flash"


def _card(item_id="i1", reason="原生木浆抽纸，清洁随手抽"):
    return {"user_id": "u1", "item_id": item_id, "exposure_reason": reason,
            "evidence_fields": ["items.material", "items.functions"]}


def test_multiple_products_for_one_user_are_preserved():
    result = parse_agent_cards({"cards": [_card("i2"), _card("i1")]}, [("u1", "i1"), ("u1", "i2")])
    assert [row["item_id"] for row in result] == ["i2", "i1"]


@pytest.mark.parametrize("cards", [[_card(), _card()], [], [_card("i3")]])
def test_duplicate_missing_and_unexpected_pairs_are_rejected(cards):
    with pytest.raises(AgentResponseError):
        parse_agent_cards({"cards": cards}, [("u1", "i1"), ("u1", "i2")])


def test_duplicate_input_pair_is_rejected_before_generating():
    agent = ModelGoAgent(dry_run=True)
    context = {"user_id": "u1", "item_id": "i1", "item": {}}
    with pytest.raises(AgentResponseError, match="duplicate requested"):
        agent.generate_batch([context, context])


def test_reason_length_counts_total_characters_including_punctuation():
    reason = "纸" * 18 + "，✨"
    assert parse_agent_cards({"cards": [_card(reason=reason)]}, {"u1": "i1"})[0]["exposure_reason"] == reason


@pytest.mark.parametrize("reason", ["纸" * 21, "A" * 21, "24包抽纸", "三层抽纸", "擦手\n擦桌", 123, None])
def test_invalid_reason_text_is_rejected(reason):
    with pytest.raises(AgentResponseError):
        parse_agent_cards({"cards": [_card(reason=reason)]}, {"u1": "i1"})


def test_payload_uses_copy_brief_and_excludes_old_copy_and_unneeded_data():
    payload = ModelGoAgent(dry_run=True).build_payload([{
        "user_id": "u1", "item_id": "i1", "item": {"spec": "3层100抽×24包", "functions": ["清洁", "吸水"]},
        "user_context": {"city": "广州", "raw_behavior": {"secret": "raw-history-marker"}},
        "exposure_reason": "old-template-marker", "gold": "gold-label-marker",
    }])
    content = payload["messages"][1]["content"]
    request = json.loads(content)
    brief = request["contexts"][0]["copy_brief"]
    assert "items.spec" not in brief["product_facts"]
    assert "3层100抽×24包" not in content
    assert "items.functions" in brief["evidence_allowlist"]
    assert "old-template-marker" not in content
    assert "raw-history-marker" not in content
    assert "gold-label-marker" not in content
    assert request["expected_user_item_pairs"] == [{"user_id": "u1", "item_id": "i1"}]


@pytest.mark.parametrize("raw", [
    '说明：{"cards":[]}', '```json\n{"cards":[]}\n```', '{"cards":[]} {}',
    '{cards:[]}', '{"cards":[],"cards":[]}', '{"cards":[],"value":NaN}',
    '{"cards":[],"value":Infinity}', '{"cards":[],"value":1e999}',
])
def test_model_response_is_validated_as_one_whole_strict_json_document(raw):
    with pytest.raises(AgentResponseError, match="strict JSON"):
        parse_agent_cards(raw, {})
