from datetime import date

from scripts.generate_recommendation_feedback_history import generate_feedback_events


def test_feedback_events_are_deterministic_and_only_include_jev_approved_exposures():
    users = [
        {
            "user_id": "u_0001",
            "city": "杭州",
            "life_stage": "职场新人",
            "preferred_categories": "家居日用",
            "active_hours": "08:00-22:00",
        }
    ]
    items = [
        {
            "item_id": "i_0001",
            "title": "折叠收纳盒",
            "category_l1": "家居日用",
            "category_l2": "收纳整理",
            "functions": "折叠|收纳",
            "spec": "35L",
            "stock": "100",
        }
    ]
    patterns = [{"category_l2": "收纳整理", "ctr": "0.033"}]

    events_a = generate_feedback_events(users, items, patterns, count=8, seed=7, start_date=date(2026, 6, 1), days=1)
    events_b = generate_feedback_events(users, items, patterns, count=8, seed=7, start_date=date(2026, 6, 1), days=1)

    assert events_a == events_b
    assert len(events_a) == 8
    assert all(event["jev_approved"] is True for event in events_a)
    assert all(event["shown"] is True for event in events_a)
    assert all(event["jev_decision"] == "expose" for event in events_a)
    assert all(event["event_time"].startswith("2026-06-01") for event in events_a)
    assert all(isinstance(event["clicked"], bool) for event in events_a)
    assert all((event["click_time"] is not None) == event["clicked"] for event in events_a)
