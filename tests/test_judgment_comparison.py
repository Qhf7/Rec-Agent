import json
from pathlib import Path

import pytest

from agent_benchmark.judgment_comparison import build_payload, parse_judgment, run_judgment_comparison, agreement
from agent_benchmark.providers import EvaluatorConfig
from scripts.run_jev_two_question_evaluation import prepare_tasks


def configs():
    return [EvaluatorConfig("jev", "https://j.example/v1", "J_TEST", "jev-1.14.0", protocol="systemone"),
            EvaluatorConfig("other", "https://c.example/v1", "C_TEST", "test-model", reasoning_effort="max", thinking_mode="enabled")]


def answer(index=5, risk="compliant"):
    return {"answers": {"risk_type": {"choice": risk, "confidence": .9},
                        "attractiveness_score": {"score": index, "confidence": .8}}}


def test_two_questions_use_unchanged_fact_state_and_model_settings():
    tasks, requests = prepare_tasks(repeats=1)
    frozen = requests[0]["request"]
    _, jev = build_payload(configs()[0], frozen)
    _, other = build_payload(configs()[1], frozen)
    assert json.loads(jev["state"]) == json.loads(other["messages"][1]["content"])["state"]
    assert jev["questions"] == json.loads(other["messages"][1]["content"])["questions"]
    assert set(jev["questions"]) == {"risk_type", "attractiveness_score"}
    assert other["reasoning_effort"] == "max" and other["thinking"] == {"type": "enabled"}
    result = parse_judgment(configs()[0], answer(4), tasks[0]["fact_bundle"])
    assert result["attractiveness_score"] == 45 and result["decision"] == "rewrite"
    result = parse_judgment(configs()[0], answer(5), tasks[0]["fact_bundle"])
    assert result["attractiveness_score"] == 56 and result["decision"] == "expose"


def test_invalid_answer_usage_preserved_and_missing_pairs_excluded(tmp_path):
    def transport(config, endpoint, payload, timeout):
        data = answer()
        if config.name == "other":
            del data["answers"]["risk_type"]
            data = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data), "reasoning_content": "hidden"}}]}
        data["usage"] = {"input_tokens": 100, "output_tokens": 20}
        return {"status": 200, "body": json.dumps(data)}
    summary = run_judgment_comparison(configs(), tmp_path / "out", limit=1, transport=transport)
    assert summary["requests"] == 2 and summary["evaluators"]["other"]["parse_failures"] == 1
    value = summary["jev_comparison"]["comparisons"]["other"]
    assert value["planned_pairs"] == 1 and value["valid_pairs"] == 0
    results = json.loads((tmp_path / "out/results.json").read_text())
    assert all(r["usage"]["total_tokens"] == 120 for r in results)
    assert len({r["input_sha256"] for r in results}) == 1
    assert "hidden" not in "".join(p.read_text() for p in (tmp_path / "out").rglob("response.json"))


def test_disagreement_is_descriptive_not_jev_accuracy():
    rows = [{"case_id": "c", "kind": name, "status": "ok", "input_sha256": "same",
             "decision": {"risk_type": "compliant", "attractiveness_score": score, "decision": decision}}
            for name, score, decision in [("jev", 49, "rewrite"), ("other", 56, "expose")]]
    result = agreement(rows)["comparisons"]["other"]
    assert result["risk_agreement_valid"] == 1 and result["decision_agreement_valid"] == 0
    assert result["appeal_mean_absolute_difference"] == 7
    rows[1]["input_sha256"] = "changed"
    with pytest.raises(ValueError, match="input mismatch"):
        agreement(rows)
