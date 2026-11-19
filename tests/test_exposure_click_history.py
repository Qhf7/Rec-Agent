from pathlib import Path

import pytest

from generate_exposure_click_history import generate_history


ROOT = Path(__file__).resolve().parents[1]


def _load_jsonl(path: Path):
    import json

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_history_is_deterministic_and_preserves_aggregate_totals():
    candidates = _load_jsonl(ROOT / "reason_candidates_full.jsonl")[:3]
    results = _load_jsonl(ROOT / "result_jev_full.jsonl")[:3]
    exposure = _load_jsonl(ROOT / "exposure_log_full.jsonl")[:3]

    rows_a = generate_history(candidates, results, exposure, seed=19, days=5)
    rows_b = generate_history(candidates, results, exposure, seed=19, days=5)

    assert rows_a == rows_b
    assert len(rows_a) == 15
    for reason_id in {row["reason_id"] for row in rows_a}:
        history_rows = [row for row in rows_a if row["reason_id"] == reason_id]
        aggregate = next(row for row in exposure if row["reason_id"] == reason_id)
        assert sum(row["exposure_count"] for row in history_rows) == aggregate["exposure_count"]
        assert sum(row["click_count"] for row in history_rows) == aggregate["click_count"]
        assert sum(row["order_count"] for row in history_rows) == aggregate["order_count"]
        assert all(row["click_count"] <= row["exposure_count"] for row in history_rows)
        assert all(row["order_count"] <= row["click_count"] for row in history_rows)


def test_blocked_reason_has_no_exposure_or_clicks():
    candidates = [{"reason_id": "r1", "user_id": "u1", "item_id": "i1"}]
    results = [{"reason_id": "r1", "decision": "block", "risk_type": "absolute_claim", "judge_score": 0.9}]
    exposure = [{
        "reason_id": "r1", "decision": "block", "judge_score": 0.9,
        "exposed": False, "exposure_count": 0, "click_count": 0,
        "add_cart_count": 0, "order_count": 0, "refund_count": 0, "complaint_count": 0,
    }]

    rows = generate_history(candidates, results, exposure, seed=7, days=2)

    assert len(rows) == 2
    assert all(row["exposed"] is False for row in rows)
    assert all(row["exposure_count"] == row["click_count"] == 0 for row in rows)


def test_exposure_history_does_not_use_attractiveness_as_risk_severity():
    with pytest.raises(ValueError, match="risk-severity judge_score"):
        generate_history(
            [{"reason_id": "r1", "user_id": "u_0001", "item_id": "i_0001"}],
            [{"reason_id": "r1", "decision": "expose", "risk_type": "compliant",
              "compliance": "Y", "attractiveness_score": 90}],
            [{"reason_id": "r1", "exposed": True, "exposure_count": 100,
              "click_count": 10, "add_cart_count": 1, "order_count": 1,
              "refund_count": 0, "complaint_count": 0}],
        )

