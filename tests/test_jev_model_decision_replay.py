import csv
import hashlib
import json
from copy import deepcopy

import pytest

from scripts.replay_jev_model_decisions import load_frozen_comparison, replay_model_decisions
from scripts.run_jev_review_comparison import FIXTURE_PATH, IDENTITY_KEYS, prepare_tasks


def _raw(decision):
    choices = {
        "q1_identity": "valid", "q2_fact_support": "unsupported", "q3_expression_risk": "blocking",
        "q4_commercial_accuracy": "not_mentioned", "q5_context_relevance": "relevant",
        "q6_safety_gate": "human_review", "q7_final_decision": decision, "risk_type": "compliant",
    }
    answers = {key: {"choice": value, "confidence": 0.01} for key, value in choices.items()}
    answers["judge_score"] = {"score": 2, "confidence": 0.02}
    return json.dumps({"model": "jev-1.14.0", "answers": answers}, ensure_ascii=False, indent=2)


def _setup(tmp_path):
    fixture = tmp_path / "fixture.json"
    document = json.loads(FIXTURE_PATH.read_text())
    document["cases"] = document["cases"][:1]
    fixture.write_text(json.dumps(document), encoding="utf-8")
    tasks, requests = prepare_tasks(fixture_path=fixture, repeats=2)
    source = tmp_path / "source"
    source.mkdir()
    manifest = {"model": "jev-1.14.0", "tasks": tasks}
    responses = []
    for task, decision in zip(tasks, ("expose", "rewrite", "human_review", "block")):
        responses.append({**{key: task[key] for key in IDENTITY_KEYS}, "response_body": _raw(decision)})
    (source / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (source / "requests.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in requests), encoding="utf-8")
    (source / "responses.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in responses), encoding="utf-8")
    return source, tasks, responses


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_replay_preserves_all_four_q7_choices_and_source_files_without_network(tmp_path, monkeypatch):
    source, tasks, responses = _setup(tmp_path)
    original_files = {path.name: path.read_bytes() for path in source.iterdir()}
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_kw: pytest.fail("offline replay called network"))
    monkeypatch.setattr("jev_adapter.JevAdapter.judge", lambda *_a, **_kw: pytest.fail("offline replay called judge"))
    output = tmp_path / "replayed"
    report = replay_model_decisions(source, output)
    assert report["mode"] == "replay"
    assert report["network_calls"] == 0
    assert report["source_task_count"] == report["source_model_response_count"] == report["successful_decision_count"] == 4
    assert report["error_count"] == 0
    assert report["decision_source"] == "jev_model"
    assert report["source_responses_sha256"] == hashlib.sha256(original_files["responses.jsonl"]).hexdigest()
    assert original_files == {path.name: path.read_bytes() for path in source.iterdir()}
    decisions = _rows(output / "decisions.jsonl")
    assert [row["decision"]["decision"] for row in decisions] == ["expose", "rewrite", "human_review", "block"]
    for row, raw in zip(decisions, responses):
        assert row["decision"]["decision"] == json.loads(raw["response_body"])["answers"]["q7_final_decision"]["choice"]
        assert row["decision"]["decision_source"] == "jev_model"
        assert "confidence_threshold" not in row["decision"]
        assert "gate_reasons" not in row["decision"]
    with (output / "comparison_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 4
    assert all(row["native_q7"] == row["decision"] for row in csv_rows)
    assert all(row["decision_confidence"] == "0.01" for row in csv_rows)
    for group in report["groups"].values():
        assert group["native_q7_distribution"] == group["final_decision_distribution"]


def test_missing_or_invalid_response_records_error_without_creating_disposition(tmp_path, monkeypatch):
    source, tasks, responses = _setup(tmp_path)
    responses[0]["response_body"] = "{malformed model response"
    responses.pop(1)
    (source / "responses.jsonl").write_text("".join(json.dumps(row) + "\n" for row in responses), encoding="utf-8")
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_kw: pytest.fail("offline replay called network"))
    output = tmp_path / "replayed"
    report = replay_model_decisions(source, output)
    assert report["status"] == "completed_with_errors"
    assert report["error_count"] == 2
    assert report["successful_decision_count"] == 2
    assert [row["decision"]["decision"] for row in _rows(output / "decisions.jsonl")] == ["human_review", "block"]
    assert {row["run_id"] for row in _rows(output / "errors.jsonl")} == {tasks[0]["run_id"], tasks[1]["run_id"]}


@pytest.mark.parametrize("tamper", ["facts", "rule_features", "lexicon_hits", "missing_hash"])
def test_replay_checks_complete_frozen_fact_hash_before_writing_output(tmp_path, tamper):
    source, tasks, _ = _setup(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text())
    task = manifest["tasks"][0]
    if tamper == "facts":
        task["fact_bundle"]["item"]["material"] = "invented"
    elif tamper == "rule_features":
        task["fact_bundle"]["rule_features"]["price_mismatch"] = True
    elif tamper == "lexicon_hits":
        task["fact_bundle"]["lexicon_hits"].append({"term": "虚构", "canonical_term": "虚构", "risk_type": "absolute_claim", "severity": "high", "match_type": "exact"})
    else:
        task.pop("facts_sha256")
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "replayed"
    with pytest.raises(ValueError, match="facts SHA256"):
        replay_model_decisions(source, output)
    assert not output.exists()


@pytest.mark.parametrize("tamper,match", [
    ("response_metadata", "metadata differs"), ("duplicate_response", "duplicate response"),
    ("unknown_response", "unknown or duplicate"), ("duplicate_task", "run_id must be unique"),
    ("bundle_reason_id", "reason_id differs"),
])
def test_replay_rejects_identity_drift(tmp_path, tamper, match):
    source, tasks, responses = _setup(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text())
    if tamper == "response_metadata":
        responses[0]["repeat"] = 3
    elif tamper == "duplicate_response":
        responses.append(deepcopy(responses[0]))
    elif tamper == "unknown_response":
        responses[0]["run_id"] = "invented"
    elif tamper == "duplicate_task":
        manifest["tasks"].append(deepcopy(tasks[0]))
    else:
        manifest["tasks"][0]["fact_bundle"]["reason_id"] = "invented"
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "responses.jsonl").write_text("".join(json.dumps(row) + "\n" for row in responses), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_frozen_comparison(source)


def test_replay_refuses_to_overwrite_existing_result(tmp_path):
    source, _, _ = _setup(tmp_path)
    output = tmp_path / "replayed"
    output.mkdir()
    (output / "decisions.jsonl").write_text("keep this")
    with pytest.raises(ValueError, match="already exists"):
        replay_model_decisions(source, output)
    assert (output / "decisions.jsonl").read_text() == "keep this"


@pytest.mark.parametrize("tamper", ["reason_text", "reason_id", "question_version"])
def test_replay_rejects_task_rebinding_to_a_different_candidate_or_question(tmp_path, tamper):
    source, _, _ = _setup(tmp_path)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    task = manifest["tasks"][0]
    if tamper == "reason_text":
        task["fact_bundle"]["exposure_reason"] = "改写后的完全不同推荐理由"
        task["fact_bundle"]["generated_reason"] = task["fact_bundle"]["exposure_reason"]
    elif tamper == "reason_id":
        task["reason_id"] = task["fact_bundle"]["reason_id"] = "r_rebound"
    else:
        task["question_version"] = manifest["tasks"][1]["question_version"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "replayed"
    with pytest.raises(ValueError, match="request (payload|metadata) differs"):
        replay_model_decisions(source, output)
    assert not output.exists()


@pytest.mark.parametrize("tamper,match", [
    ("missing_file", "requests.jsonl is required"), ("missing_request", "missing frozen request"),
    ("duplicate_request", "duplicate request"), ("unknown_request", "unknown or duplicate request"),
    ("metadata", "request metadata differs"), ("model", "request payload differs"),
    ("candidate", "request payload differs"), ("trace", "request payload differs"),
    ("question", "request payload differs"),
])
def test_replay_checks_frozen_request_identity_and_full_payload(tmp_path, tamper, match):
    source, _, _ = _setup(tmp_path)
    request_path = source / "requests.jsonl"
    requests = _rows(request_path)
    if tamper == "missing_file":
        request_path.unlink()
    else:
        if tamper == "missing_request":
            requests.pop()
        elif tamper == "duplicate_request":
            requests.append(deepcopy(requests[0]))
        elif tamper == "unknown_request":
            requests[0]["run_id"] = "invented"
        elif tamper == "metadata":
            requests[0]["repeat"] = True
        elif tamper == "model":
            requests[0]["request"]["model"] = "another-model"
        elif tamper == "question":
            requests[0]["request"]["questions"]["q2_fact_support"]["instructions"] += " altered"
        else:
            payload = requests[0]["request"]
            state = json.loads(payload["state"])
            if tamper == "candidate":
                state["candidate"]["exposure_reason"] = state["candidate"]["generated_reason"] = "changed"
            else:
                state["trace"]["agent_version"] = "another-agent"
            payload["state"] = json.dumps(state)
        request_path.write_text("".join(json.dumps(row) + "\n" for row in requests), encoding="utf-8")
    output = tmp_path / "replayed"
    with pytest.raises(ValueError, match=match):
        replay_model_decisions(source, output)
    assert not output.exists()


def test_replay_accepts_equivalent_state_object_in_frozen_request(tmp_path):
    source, _, _ = _setup(tmp_path)
    request_path = source / "requests.jsonl"
    requests = _rows(request_path)
    for record in requests:
        record["request"]["state"] = json.loads(record["request"]["state"])
    request_path.write_text("".join(json.dumps(row, indent=None) + "\n" for row in requests), encoding="utf-8")
    report = replay_model_decisions(source, tmp_path / "replayed")
    assert report["successful_decision_count"] == 4
    assert report["error_count"] == report["network_calls"] == 0
