import json
from pathlib import Path

from evaluate_exposure import generate_exposure_records, summarize_calibration
from compare_baselines import compare_results


def test_compare_results_reports_disagreements():
    rule = [{
        "reason_id": "r1", "decision": "expose", "risk_type": "compliant",
        "evidence": ["fact_bundle.item.functions"], "judge_score": 0.02,
        "escalated": False, "model_version": "rule-baseline-v1", "score_name": "rule-compliance-v1"
    }]
    jev = [{
        "reason_id": "r1", "decision": "rewrite", "risk_type": "absolute_claim",
        "evidence": ["lexicon.absolute_claim:第一"], "judge_score": 0.7,
        "escalated": True, "model_version": "jev-1.14.0", "score_name": "jev-compliance-v1"
    }]
    labels = [{"reason_id": "r1", "gold_decision": "rewrite", "gold_risk_type": "absolute_claim"}]

    report = compare_results(rule, jev, labels)

    assert report["sample_count"] == 1
    assert report["decision_disagreements"] == 1
    assert report["risk_type_disagreements"] == 1
    assert report["cases"][0]["reason_id"] == "r1"


def test_exposure_records_are_deterministic_and_respect_decision_gate():
    candidates = [{
        "reason_id": "r1", "user_context": {"recent_categories": ["家居日用"]},
        "item_attrs_returned": {"category": "家居日用", "target_tags": ["收纳"]},
        "generated_reason": "家居收纳更方便"
    }]
    results = [{
        "reason_id": "r1", "decision": "block", "risk_type": "efficacy_or_medical_claim",
        "judge_score": 0.95, "escalated": False
    }]

    latent_a, exposure_a = generate_exposure_records(candidates, results, seed=7)
    latent_b, exposure_b = generate_exposure_records(candidates, results, seed=7)

    assert latent_a == latent_b
    assert exposure_a == exposure_b
    assert exposure_a[0]["exposed"] is False
    assert exposure_a[0]["exposure_count"] == 0


def test_calibration_summary_has_score_buckets():
    rows = [{
        "reason_id": "r1", "judge_score": 0.1, "exposed": True,
        "exposure_count": 100, "refund_count": 2, "complaint_count": 1, "order_count": 20
    }]
    report = summarize_calibration(rows, rows)

    assert report["bucket_count"] == 10
    assert len(report["buckets"]) == 10
