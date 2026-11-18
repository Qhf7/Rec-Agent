import json
import urllib.error
from copy import deepcopy

import pytest

from jev_adapter import JevAdapter, JevConfigurationError
from scripts.run_jev_review_comparison import (
    FIXTURE_PATH,
    OUTPUT_NAMES,
    VERSIONS,
    _check_ab_payloads,
    prepare_tasks,
    run_comparison,
)


def _fixture(tmp_path, count=1):
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    document["cases"] = document["cases"][:count]
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _body(request, *, invalid_answer=None):
    payload = json.loads(request.data)
    version = json.loads(payload["state"])["question_schema_version"]
    choices = {
        "q1_identity": "valid", "q2_fact_support": "partial" if version == VERSIONS[0] else "supported",
        "q3_expression_risk": "clean", "q4_commercial_accuracy": "not_mentioned",
        "q5_context_relevance": "relevant", "q6_safety_gate": "pass",
        "q7_final_decision": "expose", "risk_type": "compliant",
    }
    answers = {key: {"choice": choice, "confidence": .99} for key, choice in choices.items()}
    answers["judge_score"] = {"score": 0, "confidence": .99, "probabilities": {"0": 1, "1": 0, "2": 0}}
    if invalid_answer is not None:
        answers["q2_fact_support"] = invalid_answer
    return json.dumps({"model": payload["model"], "answers": answers}, ensure_ascii=False)


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body.encode("utf-8")


def test_default_prepare_freezes_160_requests_without_network_or_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_k: pytest.fail("prepare called network"))
    summary = run_comparison(tmp_path / "prepared")
    assert summary["planned_calls"] == 160
    assert summary["network_calls"] == summary["http_response_count"] == 0
    assert summary["status"] == "prepared"
    assert summary["decision_source"] == "jev_model"
    assert summary["accuracy_claim"] is None
    directory = tmp_path / "prepared"
    assert all((directory / name).is_file() for name in OUTPUT_NAMES)
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["case_count"] == 40 and len(manifest["tasks"]) == 160
    assert len({task["run_id"] for task in manifest["tasks"]}) == 160
    assert manifest["decision_source"] == "jev_model"
    assert "confidence_threshold" not in manifest
    requests = _rows(directory / "requests.jsonl")
    for row in requests:
        text = json.dumps(row["request"], ensure_ascii=False)
        assert all(term not in text for term in ("provisional_", "holdout", "calibration", "group_id"))
    for offset in range(0, len(requests), 4):
        _check_ab_payloads(requests[offset]["request"], requests[offset + 1]["request"])
        assert requests[offset]["question_version"] == VERSIONS[0]
        assert requests[offset + 2]["question_version"] == VERSIONS[1]


def test_controlled_pair_refuses_changed_non_q2_question_or_fact(tmp_path):
    _, requests = prepare_tasks(fixture_path=_fixture(tmp_path), repeats=1)
    left, right = [row["request"] for row in requests]
    _check_ab_payloads(left, right)
    changed = deepcopy(right)
    changed["questions"]["q3_expression_risk"]["instructions"] += " changed"
    with pytest.raises(ValueError, match="other than Q2"):
        _check_ab_payloads(left, changed)
    changed = deepcopy(right)
    state = json.loads(changed["state"])
    state["facts"]["item"]["title"] += " changed"
    changed["state"] = json.dumps(state)
    with pytest.raises(ValueError, match="changed facts"):
        _check_ab_payloads(left, changed)


@pytest.mark.parametrize("settings,match", [
    ({"workers": 0}, "workers"), ({"workers": 5}, "workers"),
    ({"max_calls": 0}, "max_calls"), ({"max_calls": 159}, "exceed"),
    ({"repeats": 0}, "repeats"), ({"timeout": float("nan")}, "timeout"),
    ({"timeout": 0}, "timeout"),
])
def test_preflight_rejects_invalid_settings_before_files_or_network(tmp_path, monkeypatch, settings, match):
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_k: pytest.fail("preflight called network"))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match=match):
        run_comparison(output, **settings)
    assert not output.exists()


def test_live_without_key_and_existing_output_fail_before_network(tmp_path, monkeypatch):
    monkeypatch.delenv("MODELGO_API_KEY", raising=False)
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_k: pytest.fail("preflight called network"))
    fixture = _fixture(tmp_path)
    output = tmp_path / "output"
    with pytest.raises(JevConfigurationError, match="MODELGO_API_KEY"):
        run_comparison(output, fixture_path=fixture, live=True)
    assert not output.exists()
    output.mkdir()
    (output / "responses.jsonl").write_text("preserve this")
    with pytest.raises(ValueError, match="already exists"):
        run_comparison(output, fixture_path=fixture)
    assert (output / "responses.jsonl").read_text() == "preserve this"


def test_optional_regressions_and_disclosure_variants_make_172_frozen_tasks(tmp_path):
    # Standalone test inputs avoid depending on ignored local desktop exports.
    for user_id in ("u_0001", "u_0199"):
        payload = {
            "user_id": user_id, "agent_version": "rec-agent-v2",
            "recommendations": [{"item_id": f"i_{number:04d}", "exposure_reason": "折叠收纳更省心",
                                 "evidence_fields": ["items.functions"]} for number in (1, 2, 3)],
        }
        (tmp_path / f"{user_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tasks, requests = prepare_tasks(include_original_six=True, original_dir=tmp_path, disclosure_controls=3)
    assert len(tasks) == len(requests) == 172
    assert sum(task["group"] == "original_six" for task in tasks) == 6
    controls = [task for task in tasks if task["group"] == "disclosure_control"]
    assert len(controls) == 6
    assert {task["ai_disclosure"] for task in controls} == {"visible", "missing"}
    assert all(task["question_version"] == VERSIONS[1] for task in controls)
    for task in controls:
        assert task["fact_bundle"]["verification_state"] == "verified"


def test_mocked_live_retains_raw_before_parser_and_reports_pair_stability(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    output = tmp_path / "live"
    monkeypatch.setenv("MODELGO_API_KEY", "private-test-credential")
    observed_raw = []

    def request(request, **_kwargs):
        assert request.get_header("Authorization") == "Bearer private-test-credential"
        raw = _body(request)
        observed_raw.append(raw)
        return _Response(raw)

    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", request)
    original_parser = JevAdapter.parse_response

    def parse_after_raw(adapter, raw, bundle, **kwargs):
        assert any(row["response_body"] == raw for row in _rows(output / "responses.jsonl"))
        return original_parser(adapter, raw, bundle, **kwargs)

    monkeypatch.setattr(JevAdapter, "parse_response", parse_after_raw)
    summary = run_comparison(output, fixture_path=fixture, live=True, workers=1)
    assert summary["planned_calls"] == summary["network_calls"] == 4
    assert summary["http_response_count"] == summary["successful_decision_count"] == 4
    assert summary["error_count"] == 0
    assert all(row["decision"]["decision"] == "expose" for row in _rows(output / "decisions.jsonl"))
    assert summary["q2_transitions_legacy_to_v2"] == {"partial -> supported": 2}
    for stability in summary["repeat_stability"].values():
        assert stability["cases_with_all_repeats_observed"] == stability["q2_unanimous_cases"] == 1
        assert stability["native_q7_unanimous_cases"] == stability["final_decision_unanimous_cases"] == 1
    assert [row["response_body"] for row in _rows(output / "responses.jsonl")] == observed_raw
    assert len({row["run_id"] for row in _rows(output / "responses.jsonl")}) == 4
    for path in output.iterdir():
        assert "private-test-credential" not in path.read_text(encoding="utf-8")
        assert '"Authorization"' not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_answer", ["bad", [], {"choice": []}])
def test_invalid_individual_answers_preserve_raw_and_finish_error_summary(tmp_path, monkeypatch, bad_answer):
    monkeypatch.setenv("MODELGO_API_KEY", "private-test-credential")
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda request, **_k: _Response(_body(request, invalid_answer=bad_answer)))
    output = tmp_path / "malformed"
    summary = run_comparison(output, fixture_path=_fixture(tmp_path), repeats=1, live=True, workers=1)
    assert summary["http_response_count"] == summary["error_count"] == 2
    assert summary["successful_decision_count"] == 0
    assert summary["response_parse_error_count"] == 2
    assert summary["repeat_stability"][VERSIONS[1]]["cases_with_all_repeats_observed"] == 0
    assert len(_rows(output / "responses.jsonl")) == 2
    assert all(row["stage"] == "response_parse" for row in _rows(output / "errors.jsonl"))
    assert json.loads((output / "summary.json").read_text())["status"] == "completed_with_errors"


def test_http_failure_is_recorded_without_fabricated_response_and_redacts_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELGO_API_KEY", "private-test-credential")

    def fail(*_args, **_kwargs):
        raise urllib.error.URLError("network failed private-test-credential")

    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", fail)
    output = tmp_path / "failed"
    summary = run_comparison(output, fixture_path=_fixture(tmp_path), repeats=1, live=True, workers=1)
    assert summary["network_calls"] == summary["error_count"] == 2
    assert summary["http_response_count"] == summary["successful_decision_count"] == 0
    assert (output / "responses.jsonl").read_text() == ""
    assert all(row["stage"] == "request" for row in _rows(output / "errors.jsonl"))
    assert "private-test-credential" not in (output / "errors.jsonl").read_text()
    assert "[REDACTED]" in (output / "errors.jsonl").read_text()


def test_response_key_echo_is_redacted_without_changing_parse_input(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELGO_API_KEY", "private-test-credential")

    def request(request, **_kwargs):
        payload = json.loads(_body(request))
        payload["unexpected_server_note"] = "private-test-credential"
        return _Response(json.dumps(payload))

    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", request)
    output = tmp_path / "redacted"
    summary = run_comparison(output, fixture_path=_fixture(tmp_path), repeats=1, live=True, workers=1)
    assert summary["successful_decision_count"] == 2
    records = _rows(output / "responses.jsonl")
    assert all(row["credential_redacted"] is True for row in records)
    assert "private-test-credential" not in (output / "responses.jsonl").read_text()
