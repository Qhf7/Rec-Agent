from copy import deepcopy
import json

import pytest

from agent_benchmark.judges import fingerprint, questions
from agent_benchmark.providers import (EvaluatorConfig, SYSTEM_INSTRUCTION, build_request,
                                      extract_answer, run_frozen_comparison, usage_of)


def answers():
    return {"answers": {key: {"choice": next(iter(definition["criteria"])), "confidence": .8}
                         for key, definition in questions().items()}}


def frozen(tmp_path, count=1):
    cases = []
    for index in range(count):
        state = {"schema_version": "test", "task": {"task_id": f"t{index}"}, "trace": {"calls": [], "final": {}}, "questions": questions()}
        cases.append({"case_id": f"case_{index:03}", "task_id": f"t{index}", "state": state,
                      "input_sha256": fingerprint(state),
                      "reference": {key: value["choice"] for key, value in answers()["answers"].items()}})
    path = tmp_path / "source.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    return path, cases


def configs():
    return [EvaluatorConfig("deepseek", "https://ds.example/v1", "DS_TEST_ENV", "deepseek-test", disable_thinking=True, max_output_tokens=500, temperature=0),
            EvaluatorConfig("sol", "https://third.example/v1", "SOL_TEST_ENV", "gpt-6.1-sol", protocol="responses", reasoning_effort="ultra", max_output_tokens=16384),
            EvaluatorConfig("jev", "https://jev.example/v1", "JEV_TEST_ENV", "jev-1.14.0", protocol="systemone")]


def response_envelope(config, content=None):
    content = json.dumps(answers()) if content is None else content
    usage = {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100, "prompt_tokens_details": {"cached_tokens": 30}, "completion_tokens_details": {"reasoning_tokens": 10}}
    if config.protocol == "systemone":
        return {**answers(), "model": config.model, "usage": usage}
    if config.protocol == "responses":
        return {"id": "resp_test", "status": "completed", "model": config.model, "reasoning": {"effort": "xhigh"},
                "output": [{"type": "reasoning", "summary": [{"text": "hidden summary"}]}, {"type": "message", "content": [{"type": "output_text", "text": content}]}],
                "usage": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140, "input_tokens_details": {"cached_tokens": 60}, "output_tokens_details": {"reasoning_tokens": 30}},
                "customer_usage": {"estimated": True, "source": "client_request"}}
    return {"id": "chat_test", "model": config.model, "usage": usage, "choices": [{"finish_reason": "stop", "message": {"content": content, "reasoning_content": "do not save hidden text"}}]}


def test_three_payloads_reuse_exact_frozen_state_and_protocol_settings(tmp_path):
    _, cases = frozen(tmp_path)
    state = cases[0]["state"]
    ds, sol, jev = configs()
    endpoint, payload = build_request(ds, state)
    assert endpoint.endswith("/chat/completions")
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 500
    assert payload["temperature"] == 0
    assert payload["messages"][0]["content"] == SYSTEM_INSTRUCTION
    assert json.loads(payload["messages"][1]["content"]) == state
    endpoint, payload = build_request(sol, state)
    assert endpoint.endswith("/responses")
    assert payload["reasoning"] == {"effort": "ultra"}
    assert payload["max_output_tokens"] == 16384
    assert payload["text"]["format"]["type"] == "json_object"
    assert json.loads(payload["input"][0]["content"]) == state
    endpoint, payload = build_request(jev, state)
    assert endpoint.endswith("/systemone")
    assert json.loads(payload["state"]) == state
    assert payload["questions"] == questions()


def test_chat_ultra_effort_and_completion_budget_are_not_silently_disabled(tmp_path):
    _, cases = frozen(tmp_path)
    config = EvaluatorConfig("sol", "https://third.example/v1", "SOL_TEST_ENV", "gpt-6.1-sol-ultra", reasoning_effort="ultra", max_output_tokens=16384)
    _, payload = build_request(config, cases[0]["state"])
    assert payload["reasoning_effort"] == "ultra"
    assert payload["max_completion_tokens"] == 16384
    assert "thinking" not in payload
    assert "max_tokens" not in payload


def test_responses_usage_preserves_cache_reasoning_and_estimation():
    envelope = response_envelope(configs()[1])
    usage = usage_of(envelope)
    assert [usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "reasoning_tokens")] == [100, 40, 140, 60, 30]
    assert usage["total_tokens_source"] == "reported"
    assert usage["estimated"] is True
    assert usage["measurement_source"] == "client_request"
    assert usage_of({})["total_tokens"] is None
    derived = usage_of({"usage": {"input_tokens": 1, "output_tokens": 2}})
    assert derived["total_tokens"] == 3
    assert derived["total_tokens_source"] == "derived_input_plus_output"


def test_frozen_executor_shares_cases_and_keeps_metadata(tmp_path):
    path, cases = frozen(tmp_path, 2)
    captured = []
    def transport(config, endpoint, payload, timeout):
        captured.append((config.name, deepcopy(payload)))
        return {"status": 200, "headers": {"X-Request-Id": "request-test"}, "body": json.dumps(response_envelope(config))}
    summary = run_frozen_comparison(path, configs(), tmp_path / "run", repeats=2, workers=2, transport=transport)
    assert len(captured) == 12
    assert summary["case_count"] == 2
    assert all(item["valid_answers"] == 4 for item in summary["evaluators"].values())
    assert summary["evaluators"]["sol"]["reasoning_effort_mismatches"] == 4
    assert summary["evaluators"]["sol"]["estimated_usage_requests"] == 4
    saved = json.loads((tmp_path / "run/manifest.json").read_text())
    assert saved["cases"] == cases
    assert saved["automatic_retries"] == 0
    text = "".join(p.read_text() for p in (tmp_path / "run").rglob("*.json"))
    assert "do not save hidden text" not in text
    assert "hidden summary" not in text
    rows = json.loads((tmp_path / "run/results.json").read_text())
    assert all(row["metadata"]["request_id"] == "request-test" for row in rows)


def test_invalid_answer_retains_response_usage_and_failure_denominator(tmp_path):
    path, _ = frozen(tmp_path, 2)
    config = configs()[0]
    calls = []
    def transport(config, endpoint, payload, timeout):
        calls.append(1)
        return {"status": 200, "body": json.dumps(response_envelope(config, "not valid JSON" if len(calls) == 1 else None))}
    summary = run_frozen_comparison(path, [config], tmp_path / "run", workers=1, transport=transport)
    metric = summary["evaluators"]["deepseek"]
    assert metric["parse_failures"] == 1
    assert metric["valid_answers"] == 1
    assert metric["agreement_all_attempts"]["task_completed"] == .5
    assert metric["agreement_valid_only"]["task_completed"] == 1
    assert metric["total_tokens"]["reported"] == 2
    assert metric["total_tokens"]["sum"] == 200
    assert len(list((tmp_path / "run").glob("*/response.json"))) == 2


def test_http_failure_keeps_raw_local_body_and_safe_public_error(tmp_path):
    path, _ = frozen(tmp_path)
    def transport(*args):
        return {"status": 503, "headers": {"Retry-After": "5"}, "body": "upstream diagnostic internal-private-text"}
    summary = run_frozen_comparison(path, [configs()[0]], tmp_path / "run", transport=transport)
    assert summary["evaluators"]["deepseek"]["transport_failures"] == 1
    assert list((tmp_path / "run").glob("*/response.txt"))[0].read_text() == "upstream diagnostic internal-private-text"
    rows = (tmp_path / "run/results.json").read_text()
    assert "internal-private-text" not in rows
    assert json.loads(rows)[0]["usage"]["total_tokens"] is None


@pytest.mark.parametrize("change", ["hash", "questions"])
def test_changed_frozen_cases_fail_before_any_transport(tmp_path, change):
    path, _ = frozen(tmp_path)
    manifest = json.loads(path.read_text())
    if change == "hash":
        manifest["cases"][0]["state"]["trace"] = {"tampered": True}
    else:
        manifest["cases"][0]["state"]["questions"] = {}
        manifest["cases"][0]["input_sha256"] = fingerprint(manifest["cases"][0]["state"])
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        run_frozen_comparison(path, configs(), tmp_path / "run", transport=lambda *a: pytest.fail("must not send"))
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("protocol,marker", [("chat_completions", "length"), ("responses", "incomplete")])
def test_truncation_is_failure_even_with_parseable_partial_answer(protocol, marker):
    config = EvaluatorConfig("test", "https://example/v1", "TEST_ENV", "test", protocol=protocol)
    envelope = response_envelope(config)
    if protocol == "responses":
        envelope["status"] = marker
    else:
        envelope["choices"][0]["finish_reason"] = marker
    with pytest.raises(ValueError):
        extract_answer(config, envelope)


def test_configs_contain_env_reference_and_reject_literal_secret_fields():
    config = configs()[0]
    assert config.public()["api_key_env"] == "DS_TEST_ENV"
    with pytest.raises(TypeError):
        EvaluatorConfig(**{**config.public(), "api_key": "not-allowed"})
    with pytest.raises(ValueError):
        EvaluatorConfig("bad", "https://example/v1", "TEST_ENV", "model", reasoning_effort="ultra", disable_thinking=True)


def test_single_pass_does_not_claim_repeat_consistency(tmp_path):
    path, _ = frozen(tmp_path)
    def transport(config, endpoint, payload, timeout):
        return {"status": 200, "body": json.dumps(response_envelope(config))}
    summary = run_frozen_comparison(path, [configs()[0]], tmp_path / "run", repeats=1, transport=transport)
    metric = summary["evaluators"]["deepseek"]
    assert metric["valid_answers"] == 1
    assert metric["complete_repeat_cases"] is None
    assert metric["repeat_unanimous"] is None
