"""Verify current two-question evaluation snapshots and response-bound replay."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jev_adapter import JevConfigurationError
from scripts.run_jev_two_question_evaluation import (
    HARNESS_SAMPLES, OUTPUT_NAMES, QUESTION_KEYS, ROOT, VERSION, replay_evaluation, run_evaluation,
)


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rewrite(path, records):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body.encode("utf-8")


def test_prepare_is_exactly_two_questions_without_network_or_expected_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_k: pytest.fail("prepare called network"))
    output = tmp_path / "prepare"
    summary = run_evaluation(output)
    assert summary["status"] == "prepared"
    assert summary["planned_calls"] == 13
    assert summary["network_calls"] == summary["http_response_count"] == 0
    assert summary["accuracy_claim"] is None
    assert all((output / name).is_file() for name in OUTPUT_NAMES)
    requests = rows(output / "requests.jsonl")
    assert len({row["run_id"] for row in requests}) == len(requests) == 13
    for record in requests:
        payload = record["request"]
        state = json.loads(payload["state"])
        assert state["question_schema_version"] == VERSION
        assert set(payload["questions"]) == QUESTION_KEYS
        assert state["questions"] == payload["questions"]
        assert set(payload["questions"]["risk_type"]["criteria"]) == {
            "compliant", "absolute_claim", "efficacy_or_medical_claim", "price_misleading",
            "missing_ai_disclosure", "off_topic",
        }
        assert all(word not in payload["state"] for word in ("expected_", "gold_label", "user_id", "case_id", "saved_harness"))
    by_run = {row["run_id"]: json.loads(row["request"]["state"]) for row in requests}
    assert [by_run[f"h{n:02}__r1"]["candidate"]["exposure_reason"] for n in range(1, 4)] == [row[1] for row in HARNESS_SAMPLES]
    controls = [by_run[f"d{n:02}__r1"] for n in range(1, 4)]
    assert [row["facts"]["disclosure"]["flag"] for row in controls] == [True, False, None]
    assert len({json.dumps(row["facts"]["item"], sort_keys=True) for row in controls}) == 1
    assert "人工金标" in (output / "results.md").read_text(encoding="utf-8")
    assert (output / "results.csv").read_text(encoding="utf-8-sig").splitlines()[0].startswith("run_id,")


def test_live_replays_across_processes_and_rejects_changed_requests_and_responses(tmp_path, monkeypatch):
    key = "mock-secret-to-redact"
    monkeypatch.setenv("MODELGO_API_KEY", key)
    output = tmp_path / "live"

    def mock_urlopen(request, **_kwargs):
        payload = json.loads(request.data)
        state = json.loads(payload["state"])
        identifier = state["candidate"]["reason_id"]
        if identifier == "r_two_s01":
            return Response(json.dumps({"invalid": key}))
        risk = "missing_ai_disclosure" if state["facts"]["disclosure"]["flag"] is False else "compliant"
        answers = {"risk_type": {"choice": risk, "confidence": .8},
                   "attractiveness_score": {"score": 5, "confidence": .7}}
        if identifier == "r_two_h01":
            # Service rounding sums to .99. After normalization the expected
            # API index is 49/11, mapping exactly to business score 50.
            distribution = {str(level): 0 for level in range(10)}
            distribution.update({"4": .54, "5": .45})
            answers["attractiveness_score"]["probabilities"] = distribution
        return Response(json.dumps({"model": payload["model"], "answers": answers}))

    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", mock_urlopen)
    first = run_evaluation(output, live=True, workers=2)
    assert first["planned_calls"] == first["network_calls"] == first["http_response_count"] == 13
    assert first["successful_decision_count"] == 12 and first["error_count"] == 1
    assert first["decision_counts"] == {"expose": 9, "rewrite": 3}
    result = json.loads((output / "results.json").read_text(encoding="utf-8"))["results"]
    handband = next(row for row in result if row["run_id"] == "h01__r1")
    assert (handband["attractiveness_score"], handband["compliance"], handband["decision"]) == (50, "Y", "rewrite")
    assert all(key not in path.read_text(encoding="utf-8-sig") for path in output.iterdir())
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_k: pytest.fail("replay called network"))
    replay = tmp_path / "replay"
    command = subprocess.run([
        sys.executable, str(ROOT / "scripts/run_jev_two_question_evaluation.py"),
        "--replay-dir", str(output), "--output-dir", str(replay),
    ], capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED="321"), check=False)
    assert command.returncode == 1, command.stderr
    restored = json.loads(command.stdout)
    assert restored["network_calls"] == 0 and restored["error_count"] == 1
    assert restored["decision_counts"] == first["decision_counts"]
    assert rows(replay / "decisions.jsonl") == rows(output / "decisions.jsonl")
    responses = rows(output / "responses.jsonl")
    responses[0]["response_body"] += " "
    rewrite(output / "responses.jsonl", responses)
    with pytest.raises(ValueError, match="response body hash mismatch"):
        replay_evaluation(output, tmp_path / "bad_response")
    responses[0]["response_body"] = responses[0]["response_body"][:-1]
    rewrite(output / "responses.jsonl", responses)
    requests = rows(output / "requests.jsonl")
    requests[0]["request"]["state"] += " "
    rewrite(output / "requests.jsonl", requests)
    with pytest.raises(ValueError, match="frozen request differs"):
        replay_evaluation(output, tmp_path / "bad_request")


def test_guards_key_budget_overwrite_and_repeat_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("MODELGO_API_KEY", raising=False)
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_k: pytest.fail("guard called network"))
    output = tmp_path / "output"
    with pytest.raises(JevConfigurationError, match="MODELGO_API_KEY"):
        run_evaluation(output, live=True)
    with pytest.raises(ValueError, match="exceed max_calls"):
        run_evaluation(output, max_calls=12)
    with pytest.raises(ValueError, match="repeats"):
        run_evaluation(output, repeats=True)
    assert not output.exists()
    prepared = run_evaluation(output, repeats=2)
    assert prepared["planned_calls"] == 26
    sentinel = (output / "manifest.json").read_text()
    with pytest.raises(ValueError, match="already exists"):
        run_evaluation(output)
    assert (output / "manifest.json").read_text() == sentinel
