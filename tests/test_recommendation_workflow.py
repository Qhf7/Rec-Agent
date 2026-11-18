import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from canonical_data import CANONICAL_SCHEMA_VERSION, load_canonical_items, load_canonical_users
from jev_adapter import JevAdapter
from scripts.run_recommendation_workflow import parse_recommendation_input, run_workflow

ROOT = Path(__file__).resolve().parents[1]


def harness():
    return {
        "user_id": "u_0001",
        "user_profile": {"city": "模型错误城市", "history": {"ctr": 0.99}},
        "recommendations": [{
            "item_id": "i_0001", "title": "模型错误标题",
            "exposure_reason": "折叠收纳，35L大容量更省心",
            "generated_reason": "折叠收纳，35L大容量更省心",
            "evidence_fields": ["items.spec", "items.functions"],
            "context_summary": "使用商品规格与折叠收纳功能",
            "item_attrs_returned": {"functions": ["模型编造功能"]}, "history_ctr": 0.99,
        }], "agent_version": "rec-agent-v2",
    }


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]


def write_input(tmp_path, payload=None):
    path = tmp_path / "harness.json"
    path.write_text(json.dumps(harness() if payload is None else payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_prepare_rebuilds_canonical_facts_and_never_calls_judge(tmp_path, monkeypatch):
    monkeypatch.setattr(JevAdapter, "judge", lambda *_: pytest.fail("prepare called judge"))
    report = run_workflow(write_input(tmp_path), tmp_path / "output")
    candidate = read_jsonl(report["artifacts"]["candidates"])[0]
    bundle = read_jsonl(report["artifacts"]["fact_bundles"])[0]
    request = read_jsonl(report["artifacts"]["jev_requests"])[0]
    assert report["mode"] == "prepare"
    assert report["network_calls"] == report["decision_count"] == 0
    assert candidate["item_attrs_returned"] == load_canonical_items()["i_0001"]
    assert candidate["user_context"]["city"] == load_canonical_users()["u_0001"]["city"]
    assert candidate["evidence_fields"] == harness()["recommendations"][0]["evidence_fields"]
    assert candidate["context_summary"] == harness()["recommendations"][0]["context_summary"]
    assert "ai_disclosure_flag_from_code" not in candidate
    assert bundle["verification_state"] == "unverifiable"
    assert bundle["disclosure"]["flag"] is None
    assert all(row["tool"] == "local_csv_lookup" for row in candidate["tool_trace"])
    state = json.loads(request["request"]["state"])
    assert state["candidate"]["reason_id"] == candidate["reason_id"]
    assert state["candidate"]["item_id"] == "i_0001"
    assert "模型" not in json.dumps(state, ensure_ascii=False)
    assert not any(word in json.dumps(state).lower() for word in ("history", "ctr", "click", "refund", "feedback"))
    assert "decisions" not in report["artifacts"]
    assert not any("exposure" in path.name or "feedback" in path.name for path in (tmp_path / "output").iterdir())


def test_deterministic_ids_and_explicit_disclosure(tmp_path):
    source = write_input(tmp_path)
    first = run_workflow(source, tmp_path / "one", ai_disclosure="visible")
    second = run_workflow(source, tmp_path / "two", ai_disclosure="visible")
    a = read_jsonl(first["artifacts"]["candidates"])[0]
    b = read_jsonl(second["artifacts"]["candidates"])[0]
    assert a == b
    assert a["reason_id"].startswith("r_")
    assert a["ai_disclosure_flag_from_code"] is True
    assert a["snapshot_at"].startswith("2026-06-15")
    assert first["scenario_date"] == "2026-06-15"


@pytest.mark.parametrize("user_id", ["u_9999", 1, " u_0001"])
def test_unknown_or_noncanonical_user_rejected(tmp_path, user_id):
    payload = harness()
    payload["user_id"] = user_id
    with pytest.raises(ValueError, match="user_id"):
        run_workflow(write_input(tmp_path, payload), tmp_path / "output")


@pytest.mark.parametrize("field,value,match", [
    ("item_id", "item_0001", "canonical item_id"),
    ("item_id", "i_9999", "item_id"),
    ("generated_reason", "与曝光理由不一致", "generated_reason"),
    ("exposure_reason", 123, "exposure_reason"),
    ("evidence_fields", "items.spec", "evidence_fields"),
    ("context_summary", {"ctr": 0.9}, "context_summary"),
    ("reason_id", "bad reason id", "reason_id"),
    ("decision", "expose", "audit"),
])
def test_invalid_recommendations_fail_before_write(tmp_path, field, value, match):
    payload = harness()
    payload["recommendations"][0][field] = value
    with pytest.raises(ValueError, match=match):
        run_workflow(write_input(tmp_path, payload), tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_duplicate_ids_and_non_strict_json_rejected(tmp_path):
    payload = harness()
    payload["recommendations"] *= 2
    with pytest.raises(ValueError, match="duplicate reason_id"):
        run_workflow(write_input(tmp_path, payload), tmp_path / "output")
    for text in ('{"user_id":"u_0001","user_id":"u_0002","recommendations":[]}', '{"user_id":"u_0001","recommendations":[],"score":NaN}', '```json\n{}\n```'):
        with pytest.raises(ValueError):
            parse_recommendation_input(text, input_format="harness")


def test_jsonl_validates_snapshot_drift_before_reconstruction(tmp_path):
    prepared = run_workflow(write_input(tmp_path), tmp_path / "first")
    candidate = read_jsonl(prepared["artifacts"]["candidates"])[0]
    candidate["item_attrs_returned"]["functions"] = ["伪造功能"]
    source = tmp_path / "candidates.jsonl"
    source.write_text(json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="functions"):
        run_workflow(source, tmp_path / "second", input_format="jsonl")


def test_offline_jsonl_preserves_identity(tmp_path):
    prepared = run_workflow(write_input(tmp_path), tmp_path / "first")
    source = Path(prepared["artifacts"]["candidates"])
    report = run_workflow(source, tmp_path / "second", input_format="jsonl")
    original = read_jsonl(source)[0]
    candidate = read_jsonl(report["artifacts"]["candidates"])[0]
    assert candidate["reason_id"] == original["reason_id"]
    assert candidate["data_version"] == CANONICAL_SCHEMA_VERSION
    assert candidate["exposure_reason"] == candidate["generated_reason"]


def test_jsonl_preserves_partial_snapshot_without_marking_it_complete(tmp_path):
    prepared = run_workflow(write_input(tmp_path), tmp_path / "first")
    candidate = read_jsonl(prepared["artifacts"]["candidates"])[0]
    candidate["item_attrs_returned"] = {key: candidate["item_attrs_returned"][key] for key in ("item_id", "spec")}
    candidate["user_context"] = {"city": candidate["user_context"]["city"]}
    candidate["evidence_fields"] = ["items.spec", "users.city"]
    candidate["attrs_returned_complete"] = False
    source = tmp_path / "partial.jsonl"
    source.write_text(json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8")
    report = run_workflow(source, tmp_path / "second", input_format="jsonl", ai_disclosure="visible")
    replayed = read_jsonl(report["artifacts"]["candidates"])[0]
    bundle = read_jsonl(report["artifacts"]["fact_bundles"])[0]
    assert replayed["item_attrs_returned"] == candidate["item_attrs_returned"]
    assert replayed["user_context"] == candidate["user_context"]
    assert replayed["attrs_returned_complete"] is False
    assert bundle["verification_state"] == "unverifiable"


@pytest.mark.parametrize("original_time", ["2026-06-12T09:30:00+08:00", None, "missing"])
def test_jsonl_freezes_original_time_and_empty_trace(tmp_path, original_time):
    prepared = run_workflow(write_input(tmp_path), tmp_path / "first")
    candidate = read_jsonl(prepared["artifacts"]["candidates"])[0]
    candidate["promo_computed_in_code"] = {}
    candidate["tool_trace"] = []
    if original_time == "missing":
        candidate.pop("snapshot_at")
    else:
        candidate["snapshot_at"] = original_time
    source = tmp_path / "frozen.jsonl"
    source.write_text(json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8")
    report = run_workflow(source, tmp_path / "second", input_format="jsonl", ai_disclosure="visible")
    replayed = read_jsonl(report["artifacts"]["candidates"])[0]
    bundle = read_jsonl(report["artifacts"]["fact_bundles"])[0]
    assert replayed["tool_trace"] == []
    assert ("snapshot_at" in replayed) == ("snapshot_at" in candidate)
    assert replayed.get("snapshot_at") == candidate.get("snapshot_at")
    assert bundle["snapshot_at"] == candidate.get("snapshot_at")
    assert bundle["tool_trace"] == []
    assert bundle["verification_state"] == "unverifiable"


def test_jsonl_keeps_existing_query_trace_verbatim(tmp_path):
    prepared = run_workflow(write_input(tmp_path), tmp_path / "first")
    candidate = read_jsonl(prepared["artifacts"]["candidates"])[0]
    candidate["snapshot_at"] = "2026-06-12T09:30:00+08:00"
    candidate["tool_trace"] = [{"tool": "original_export_lookup", "latency_ms": 17, "returned_fields": ["spec", "functions"]}]
    source = tmp_path / "traced.jsonl"
    source.write_text(json.dumps(candidate, ensure_ascii=False) + "\n", encoding="utf-8")
    report = run_workflow(source, tmp_path / "second", input_format="jsonl", ai_disclosure="visible")
    replayed = read_jsonl(report["artifacts"]["candidates"])[0]
    assert replayed["tool_trace"] == candidate["tool_trace"]
    assert replayed["snapshot_at"] == candidate["snapshot_at"]


def test_missing_disclosure_is_false_and_unknown_does_not_inherit_model_attestation(tmp_path):
    source = write_input(tmp_path)
    missing = run_workflow(source, tmp_path / "missing", ai_disclosure="missing")
    visible = run_workflow(source, tmp_path / "visible", ai_disclosure="visible")
    assert read_jsonl(missing["artifacts"]["candidates"])[0]["ai_disclosure_flag_from_code"] is False
    replayed = run_workflow(visible["artifacts"]["candidates"], tmp_path / "unknown", input_format="jsonl")
    assert "ai_disclosure_flag_from_code" not in read_jsonl(replayed["artifacts"]["candidates"])[0]


def test_untransmitted_history_evidence_and_existing_artifacts_are_rejected(tmp_path):
    payload = harness()
    payload["recommendations"][0]["evidence_fields"] = ["items.spec", "users.history_ctr"]
    with pytest.raises(ValueError, match="evidence"):
        run_workflow(write_input(tmp_path, payload), tmp_path / "bad")
    source = write_input(tmp_path)
    run_workflow(source, tmp_path / "existing")
    with pytest.raises(ValueError, match="already contains"):
        run_workflow(source, tmp_path / "existing")


def test_live_uses_injected_adapter_and_separate_decisions(tmp_path):
    class FakeAdapter:
        def __init__(self):
            self.calls = []
        def build_payload(self, bundle):
            return JevAdapter(dry_run=True).build_payload(bundle)
        def judge(self, bundle):
            self.calls.append(copy.deepcopy(bundle))
            return {
                "reason_id": bundle["reason_id"], "decision": "human_review",
                "risk_type": "compliant", "judge_score": 0.2,
                "evidence": ["disclosure state unknown"], "escalated": True,
                "model_version": "fake-offline", "score_name": "fake",
            }
    adapter = FakeAdapter()
    report = run_workflow(write_input(tmp_path), tmp_path / "output", live=True, adapter=adapter)
    assert len(adapter.calls) == 1
    assert report["network_calls"] == report["decision_count"] == 1
    assert read_jsonl(report["artifacts"]["decisions"])[0]["decision"] == "human_review"


def test_cli_works_outside_workspace_without_network(tmp_path):
    source = write_input(tmp_path)
    output = tmp_path / "output"
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts" / "run_recommendation_workflow.py"),
        "--input", str(source), "--output-dir", str(output),
    ], cwd=tmp_path, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["candidate_count"] == report["request_count"] == 1
    assert report["network_calls"] == 0
    assert (output / "workflow_report.json").exists()
