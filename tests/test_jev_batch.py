from run_jev_batch import run_batch


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def judge(self, bundle):
        self.calls.append(bundle["reason_id"])
        return {
            "reason_id": bundle["reason_id"],
            "decision": "expose",
            "risk_type": "compliant",
            "evidence": ["fact_bundle.item.functions"],
            "judge_score": 0.02,
            "escalated": False,
            "model_version": "jev-1.14.0",
            "score_name": "jev-compliance-v1",
        }


def test_run_batch_preserves_order_and_collects_latency():
    adapter = FakeAdapter()
    results, errors, timings = run_batch(
        [{"reason_id": "r1"}, {"reason_id": "r2"}], adapter
    )

    assert [result["reason_id"] for result in results] == ["r1", "r2"]
    assert errors == []
    assert set(timings) == {"r1", "r2"}
    assert adapter.calls == ["r1", "r2"]


def test_run_batch_isolates_one_failed_request():
    class FailingAdapter(FakeAdapter):
        def judge(self, bundle):
            if bundle["reason_id"] == "r2":
                raise RuntimeError("temporary failure")
            return super().judge(bundle)

    results, errors, timings = run_batch(
        [{"reason_id": "r1"}, {"reason_id": "r2"}], FailingAdapter()
    )

    assert [result["reason_id"] for result in results] == ["r1"]
    assert errors[0]["reason_id"] == "r2"
    assert "temporary failure" in errors[0]["error"]
    assert set(timings) == {"r1", "r2"}
