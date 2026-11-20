from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import threading
import time
import urllib.error

import pytest

from canonical_data import load_canonical_users
from ui_server import RecommendationClient, RecommendationTruncatedError, ROOT, RunManager, make_server, public_error


def wait(manager, identity):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        run = manager.get(identity)
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(.01)
    raise AssertionError("run did not complete")


@pytest.fixture
def manager(tmp_path):
    fixture = ROOT / "web/data/sample-runs.json"
    destination = tmp_path / "web/data"
    destination.mkdir(parents=True)
    destination.joinpath("sample-runs.json").write_bytes(fixture.read_bytes())
    result = RunManager(root=tmp_path, sample_delay=0)
    yield result
    result.pool.shutdown(wait=True)


@pytest.mark.parametrize("user_id,expected", [("u_0001", (2, 1)), ("u_0199", (3, 0)), ("u_0007", (3, 0))])
def test_saved_real_examples_preserve_audit_without_calls(manager, user_id, expected, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("sample must not call network"))
    saved = next(s for s in manager.samples() if s["user_id"] == user_id)
    run = wait(manager, manager.create({"user_id": user_id, "mode": "sample"})["id"])
    assert run["status"] == "completed" and run["source"] == "saved_real_evaluation"
    assert (run["summary"]["expose"], run["summary"]["rewrite"]) == expected
    assert run["network_calls"] == {"recommendation": 0, "jev": 0}
    assert [r["jev_audit"] for r in run["recommendations"]] == [r["jev_audit"] for r in saved["recommendations"]]
    assert {e["stage"] for e in run["events"]} == {"context", "generating", "auditing", "complete"}
    assert all(r["item"]["item_id"] == r["item_id"] and r["item"]["title"] == r["title"] for r in run["recommendations"])
    assert "events" not in run["history"]
    assert (manager.root / "runs/web-ui" / run["id"] / "result.json").is_file()


@pytest.mark.parametrize("mode", ["live", "sample"])
def test_unknown_user_has_no_model_calls(manager, mode):
    run = wait(manager, manager.create({"user_id": "u_9999", "mode": mode})["id"])
    assert run["status"] == "completed" and run["recommendations"] == []
    assert run["network_calls"] == {"recommendation": 0, "jev": 0}
    assert run["summary"]["total"] == 0 and run["empty_reason"]


def test_invalid_and_unavailable_requests_do_not_create_runs(manager, monkeypatch):
    monkeypatch.delenv("MODELGO_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    for payload in ({"user_id": "../secret"}, {"user_id": "u_0001", "mode": "oops"}, {"user_id": "u_0001", "api_key": "secret"}, {"user_id": "u_0002", "mode": "sample"}, {"user_id": "u_0001", "mode": "live"}):
        with pytest.raises(ValueError):
            manager.create(payload)
    assert manager.recent() == []


def test_config_reports_only_credential_presence(manager, monkeypatch):
    monkeypatch.setenv("MODELGO_API_KEY", "fixture-private-key")
    config = manager.config()
    assert config["live_available"] and config["credentials"]["jev_configured"]
    assert "fixture-private-key" not in json.dumps(config)
    assert config["user_count"] == config["item_count"] == 200


def test_live_stages_call_generator_then_independent_judge_and_keep_partial_error(manager):
    template = manager.samples()[0]["recommendations"]
    sequence = []
    class Generator:
        network_calls = 1
        def generate(self, user, history, catalog, artifacts):
            sequence.append("generate")
            assert history["event_count"] == 6
            assert len(catalog) == 36
            return [{key: r[key] for key in ("user_id", "item_id", "exposure_reason", "generated_reason", "evidence_fields", "context_summary")} for r in template]
    class Judge:
        def build_payload(self, bundle):
            from jev_adapter import JevAdapter
            return JevAdapter(api_key="", dry_run=True).build_payload(bundle)
        def judge(self, bundle):
            sequence.append("judge")
            assert "recommendation_history" not in bundle
            if bundle["item_id"] == template[1]["item_id"]:
                raise RuntimeError("private provider error Bearer secret")
            result = deepcopy(next(r["jev_audit"] for r in template if r["item_id"] == bundle["item_id"]))
            result["reason_id"] = bundle["reason_id"]
            return result
    manager.generator, manager.judge_factory = Generator(), Judge
    run = wait(manager, manager.create({"user_id": "u_0001", "mode": "live"})["id"])
    assert sequence == ["generate", "judge", "judge", "judge"]
    assert run["source"] == "live_web_harness" and run["status"] == "completed_with_errors"
    assert run["network_calls"] == {"recommendation": 1, "jev": 3}
    assert run["summary"]["errors"] == 1
    assert run["recommendations"][1]["jev_audit"] is None
    assert "secret" not in json.dumps(run)


def test_recommendation_client_repairs_once_and_enforces_actual_evidence(tmp_path, manager, monkeypatch):
    from canonical_data import load_canonical_items
    template = manager.samples()[0]["recommendations"]
    cards = [{key: r[key] for key in ("user_id", "item_id", "exposure_reason", "generated_reason", "evidence_fields")} for r in template]
    valid = {"cards": cards}
    invalid = deepcopy(valid)
    invalid["cards"][0]["exposure_reason"] = "24包随手抽"
    private = "fixture-private-key"
    monkeypatch.setenv("MODELGO_API_KEY", private)
    responses = iter([invalid, valid])
    calls = []
    class Response:
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(next(responses), ensure_ascii=False)}}]}).encode()
    def open_request(request, **kwargs):
        calls.append(request)
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", open_request)
    client = RecommendationClient()
    catalog = [load_canonical_items()[r["item_id"]] for r in template]
    result = client.generate(load_canonical_users()["u_0001"], {}, catalog, tmp_path)
    assert len(result) == 3 and len(calls) == client.network_calls == 2
    assert all(private not in p.read_text() for p in tmp_path.glob("*.json"))
    assert result[0]["exposure_reason"] == cards[0]["exposure_reason"]
    payloads = [json.loads(c.data) for c in calls]
    assert [p["max_tokens"] for p in payloads] == [8192, 16384]
    assert all(p["response_format"] == {"type": "json_object"} and p["thinking"] == {"type": "disabled"} for p in payloads)
    prompt = json.loads(payloads[0]["messages"][1]["content"])
    assert prompt["copy_boundaries"]
    assert all("copy_brief" not in candidate and "product_facts" in candidate for candidate in prompt["candidates"])


def test_reasoning_budget_exhaustion_is_retried_but_never_published(tmp_path, manager, monkeypatch):
    from canonical_data import load_canonical_items
    monkeypatch.setenv("MODELGO_API_KEY", "fixture-private-key")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": "private reasoning"}}],
                               "usage": {"completion_tokens": 8192, "completion_tokens_details": {"reasoning_tokens": 8192}}}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: Response())
    client = RecommendationClient()
    with pytest.raises(RecommendationTruncatedError):
        client.generate(load_canonical_users()["u_0001"], {}, list(load_canonical_items().values())[:3], tmp_path)
    assert client.network_calls == 2
    assert [d["finish_reason"] for d in client.diagnostics] == ["length", "length"]
    assert all(d["content_characters"] == 0 for d in client.diagnostics)
    assert "private reasoning" not in json.dumps(client.diagnostics)
    assert "长度上限" in public_error(RecommendationTruncatedError())


def test_persisted_history_and_interrupted_runs_restore_without_resuming_calls(manager, monkeypatch):
    final = wait(manager, manager.create({"user_id": "u_0001", "mode": "sample"})["id"])
    path = manager.root / "runs/web-ui" / final["id"] / "result.json"
    saved = json.loads(path.read_text())
    interrupted = deepcopy(saved)
    interrupted.update(id="b" * 32, status="running", stage="auditing", finished_at=None)
    interrupted["recommendations"][1].update(audit_status="pending", jev_audit=None)
    second = manager.root / "runs/web-ui" / interrupted["id"]
    second.mkdir()
    second.joinpath("result.json").write_text(json.dumps(interrupted))
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: pytest.fail("restoration must not resume calls"))
    restored = RunManager(root=manager.root, sample_delay=0)
    try:
        assert restored.get(final["id"])["recommendations"] == final["recommendations"]
        result = restored.get(interrupted["id"])
        assert result["status"] == result["stage"] == "error"
        assert "中断" in result["error"]
        assert result["recommendations"][0]["jev_audit"] == final["recommendations"][0]["jev_audit"]
        assert result["recommendations"][1]["audit_status"] == "error" and result["recommendations"][1]["jev_audit"] is None
        assert result["network_calls"] == interrupted["network_calls"]
    finally:
        restored.pool.shutdown(wait=True)


def test_http_api_export_origin_json_and_static_boundaries(manager, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>Rec-Agent</h1>")
    (tmp_path / "private.txt").write_text("private")
    server = make_server(0, manager=manager, static_root=static)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read().decode()
        connection.close()
        return result
    try:
        assert request("GET", "/")[0] == 200
        assert request("GET", "/%2e%2e/private.txt")[0] == 404
        assert request("GET", "/api/config", headers={"Host": "evil.example"})[0] == 403
        assert request("POST", "/api/runs", '{}', {"Content-Type": "application/json", "Origin": "https://evil.example"})[0] == 403
        assert request("POST", "/api/runs", '{}', {"Content-Type": "text/plain"})[0] == 415
        assert request("POST", "/api/runs", '{"user_id":"u_0001","user_id":"u_0007"}', {"Content-Type": "application/json"})[0] == 400
        status, _, body = request("POST", "/api/runs", json.dumps({"user_id": "u_0001", "mode": "sample"}), {"Content-Type": "application/json"})
        assert status == 202
        identity = json.loads(body)["id"]
        final = wait(manager, identity)
        assert json.loads(request("GET", "/api/runs/" + identity)[2])["status"] == "completed"
        status, headers, body = request("GET", f"/api/runs/{identity}/export")
        assert status == 200 and "attachment" in headers["Content-Disposition"]
        assert json.loads(body) == final
        assert len(json.loads(request("GET", "/api/runs")[2])["runs"]) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_provider_errors_are_redacted():
    error = urllib.error.HTTPError("https://endpoint?private-key", 401, "secret", {}, None)
    assert "401" in public_error(error)
    assert "secret" not in public_error(error) and "private-key" not in public_error(error)
