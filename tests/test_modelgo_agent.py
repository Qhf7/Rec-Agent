from modelgo_agent import ModelGoAgent, parse_agent_cards


def test_parse_agent_cards_validates_json_array_and_ids():
    raw = '{"cards":[{"user_id":"u1","item_id":"i1","generated_reason":"成都书房低噪除湿","evidence_fields":["city","functions"]}]}'
    cards = parse_agent_cards(raw, {"u1": "i1"})

    assert cards[0]["user_id"] == "u1"
    assert cards[0]["item_id"] == "i1"
    assert len(cards[0]["generated_reason"]) <= 24


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
    assert "不超过24个汉字" in payload["messages"][1]["content"]


def test_dry_run_returns_request_without_network():
    agent = ModelGoAgent(api_key="test-key", dry_run=True)
    result = agent.generate_batch([{"user_id": "u1", "item_id": "i1", "user_context": {}, "item": {}}])

    assert result["dry_run"] is True
    assert result["request"]["model"] == "deepseek-v4-flash"
