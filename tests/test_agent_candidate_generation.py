import json
import sys

import pytest

import generate_agent_candidates as generation
from canonical_data import CANONICAL_SCHEMA_VERSION, load_canonical_items, load_canonical_users
from fact_bundle import build_fact_bundle
from jev_adapter import JevAdapter
from modelgo_agent import AgentResponseError, ModelGoAgent


def _candidate(item_id="i_0006", reason_id="r_source_0001"):
    user = load_canonical_users()["u_0001"]
    return {
        "reason_id": reason_id, "user_id": "u_0001", "item_id": item_id,
        "schema_version": "rec-candidate-v2", "data_version": CANONICAL_SCHEMA_VERSION,
        "exposure_reason": "旧模板", "generated_reason": "旧模板", "source": "natural",
        "evidence_fields": ["items.category_l1"], "context_summary": "旧模板摘要",
        "user_context": {key: user[key] for key in ("city", "tags")},
        "item_attrs_returned": load_canonical_items()[item_id], "attrs_returned_complete": True,
        "promo_computed_in_code": {},
    }


def _card(item_id="i_0006"):
    return {
        "user_id": "u_0001", "item_id": item_id,
        "exposure_reason": "原生木浆抽纸，清洁随手抽",
        "evidence_fields": ["items.material", "items.functions"],
    }


def test_merge_uses_each_pair_and_replaces_stale_evidence_and_summary():
    sources = [_candidate(), _candidate("i_0001", "r_source_0002")]
    cards = [_card("i_0001"), _card()]
    cards[0]["exposure_reason"] = "折叠收纳盒，零碎小物有处放"
    rows = generation.merge_agent_cards(sources, cards, "test-model")
    assert [row["item_id"] for row in rows] == ["i_0006", "i_0001"]
    assert [row["source_reason_id"] for row in rows] == ["r_source_0001", "r_source_0002"]
    for row in rows:
        assert row["evidence_fields"] == ["items.material", "items.functions"]
        assert row["agent_evidence_fields"] == row["evidence_fields"]
        assert row["exposure_reason"] == row["generated_reason"]
        assert row["agent_version"] == "rec-agent-v2"
        assert row["generation_mode"] == "modelgo_llm_copy_v2"
        assert "旧模板" not in row["context_summary"]
        assert "items.material=" in row["context_summary"]


def test_merge_rejects_evidence_not_transmitted_in_brief():
    card = _card()
    card["evidence_fields"] = ["items.material", "items.infant_safe"]
    with pytest.raises(AgentResponseError, match="absent from copy_brief"):
        generation.merge_agent_cards([_candidate()], [card], "test-model")


def test_merge_requires_item_fact_and_exact_card_cardinality():
    with pytest.raises(AgentResponseError):
        generation.merge_agent_cards([_candidate()], [], "test-model")
    with pytest.raises(AgentResponseError, match="duplicate"):
        generation.merge_agent_cards([_candidate()], [_card(), _card()], "test-model")


def _cli_paths(tmp_path, monkeypatch, extra):
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(_candidate(), ensure_ascii=False) + "\n", encoding="utf-8")
    natural, full, report, requests = [tmp_path / name for name in ("natural.jsonl", "full.jsonl", "report.json", "requests.jsonl")]
    monkeypatch.setattr(sys, "argv", ["generate_agent_candidates.py", "--source", str(source),
                                      "--natural-output", str(natural), "--full-output", str(full),
                                      "--report", str(report), "--request-output", str(requests), *extra])
    return natural, full, report, requests


def test_model_failure_is_reported_without_copying_template(tmp_path, monkeypatch):
    class FailingAgent:
        model = "test-model"

        def __init__(self, **kwargs):
            pass

        def generate_batch(self, contexts):
            raise AgentResponseError("model unavailable")

    monkeypatch.setattr(generation, "ModelGoAgent", FailingAgent)
    natural, full, report_path, _ = _cli_paths(tmp_path, monkeypatch, ["--send"])
    with pytest.raises(SystemExit) as exc:
        generation.main()
    assert exc.value.code == 1
    report = json.loads(report_path.read_text())
    assert report["generated_natural_count"] == 0
    assert report["error_count"] == 1
    assert natural.read_text() == ""
    assert full.read_text() == ""


def test_dry_run_only_writes_request_preview_and_report(tmp_path, monkeypatch):
    natural, full, report_path, requests = _cli_paths(tmp_path, monkeypatch, [])
    natural.write_text("existing natural data\n")
    full.write_text("existing full data\n")
    generation.main()
    assert natural.read_text() == "existing natural data\n"
    assert full.read_text() == "existing full data\n"
    assert json.loads(requests.read_text())["dry_run"] is True
    assert json.loads(report_path.read_text())["generated_natural_count"] == 0


def test_contexts_do_not_pass_source_copy_to_the_model():
    context = generation.contexts_from_candidates([_candidate()])[0]
    payload = ModelGoAgent(dry_run=True).build_payload([context])
    assert "旧模板" not in payload["messages"][1]["content"]


def test_model_response_enters_independent_review_with_new_evidence_and_same_snapshot(monkeypatch):
    base = _candidate()
    base["snapshot_at"] = "2026-06-15T09:30:00+08:00"
    base["user_context"]["recent_clicked_item_ids"] = ["feedback-history-private-marker"]
    base["user_context"]["ctr"] = 0.5
    base["recommendation_history"] = {"events": [{"clicked": True}]}
    base["ai_disclosure_flag_from_code"] = True
    base["tool_trace"] = [{"tool": "get_item", "returned_fields": ["spec", "functions"]}]
    expected_reason = "原生木浆抽纸，清洁随手抽"
    expected_evidence = ["items.material", "items.functions"]
    response_content = json.dumps({"cards": [{
        "user_id": base["user_id"], "item_id": base["item_id"],
        "exposure_reason": expected_reason, "generated_reason": expected_reason,
        "evidence_fields": expected_evidence,
    }]}, ensure_ascii=False)
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": response_content}}]}).encode("utf-8")

    def fake_urlopen(request, **kwargs):
        requests.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr("modelgo_agent.urllib.request.urlopen", fake_urlopen)
    contexts = generation.contexts_from_candidates([base])
    expected_time = {"scenario_date": "2026-06-15", "snapshot_at": base["snapshot_at"], "timezone": "Asia/Shanghai"}
    assert contexts[0]["time_context"] == expected_time
    agent = ModelGoAgent(api_key="fake-key", dry_run=False)
    cards = agent.generate_batch(contexts)
    merged = generation.merge_agent_cards([base], cards, agent.model)[0]
    bundle = build_fact_bundle(merged, [])
    review_request = JevAdapter(dry_run=True).build_payload(bundle)
    review_state = json.loads(review_request["state"])

    # Only the recommendation request goes through HTTP. Jev gets a separate
    # request assembled from the merged candidate and canonical fact bundle.
    assert len(requests) == 1
    generation_input = json.loads(requests[0]["messages"][1]["content"])
    scene = generation_input["contexts"][0]["copy_brief"]["scene_facts"]
    for key, value in expected_time.items():
        assert scene[f"time_context.{key}"] == value
    assert bundle["time_context"] == review_state["facts"]["time_context"] == expected_time
    assert review_state["trace"]["snapshot_at"] == base["snapshot_at"]
    assert review_state["candidate"]["exposure_reason"] == expected_reason
    assert review_state["candidate"]["generated_reason"] == expected_reason
    assert review_state["candidate"]["evidence_fields"] == expected_evidence
    assert merged["context_summary"].startswith("文案依据：items.material=")
    assert "旧模板" not in merged["context_summary"]
    for serialized in (json.dumps(generation_input), review_request["state"]):
        assert "feedback-history-private-marker" not in serialized
        assert "recent_clicked_item_ids" not in serialized
        assert "recommendation_history" not in serialized
        assert '"ctr"' not in serialized
