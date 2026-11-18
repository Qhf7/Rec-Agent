from mcp_server import (
    get_item,
    get_promo,
    get_user_recommendation_history,
    get_session_context,
    get_user_behavior,
    get_user_profile,
    search_items,
)


def test_get_user_profile_returns_structured_profile():
    profile = get_user_profile("u_0007")

    assert profile["found"] is True
    assert profile["user_id"] == "u_0007"
    assert profile["city"] == "成都"
    assert "食品生鲜" in profile["preferred_categories"]


def test_get_user_behavior_returns_cart_and_search_context():
    behavior = get_user_behavior("u_0007")

    assert behavior["found"] is True
    assert "i_0092" in behavior["recent_cart_item_ids"]
    assert behavior["last_search_terms"] == ["大米", "家用"]


def test_search_items_matches_title_and_category():
    results = search_items(query="五常大米", limit=5)

    assert results
    matched = next(item for item in results if item["item_id"] == "i_0061")
    assert matched["category_l3"] == "大米"


def test_get_item_and_active_promo_are_read_only_structured_results():
    item = get_item("i_0001")
    promo = get_promo(item_id="i_0001", as_of="2026-06-15")

    assert item["found"] is True
    assert item["title"] == "栖物 可折叠防尘收纳盒 35L 奶油白"
    assert item["schema_version"] == "canonical-2026-06-15-v1"
    assert item["data_version"] == "canonical-2026-06-15-v1"
    assert promo["active"] is True
    assert promo["rules"][0]["rule_id"] == "P010"


def test_unknown_user_and_item_do_not_invent_data():
    assert get_user_profile("u_9999") == {"found": False, "user_id": "u_9999"}
    assert get_item("i_9999") == {"found": False, "item_id": "i_9999"}


def test_session_context_declares_scenario_date():
    context = get_session_context()

    assert context["scenario_date"] == "2026-06-15"
    assert context["timezone"] == "Asia/Shanghai"


def test_recommendation_history_reports_warm_and_cold_start_users():
    warm = get_user_recommendation_history("u_0001", days=30, limit=5)
    cold = get_user_recommendation_history("u_0199", days=30, limit=5)

    assert warm["history_status"] == "warm"
    assert warm["history_available"] is True
    assert warm["events"]
    assert all(event["jev_approved"] is True for event in warm["events"])
    assert set(warm["recent_clicked_item_ids"]).issubset(set(warm["recent_shown_item_ids"]))
    assert 0 <= warm["smoothed_ctr"] <= 1
    assert cold["history_status"] == "cold_start"
    assert cold["history_available"] is False
    assert cold["events"] == []

    window = get_user_recommendation_history("u_0001", days=2, limit=20, as_of="2026-06-05")
    assert all("2026-06-04" <= event["event_date"] <= "2026-06-05" for event in window["events"])
