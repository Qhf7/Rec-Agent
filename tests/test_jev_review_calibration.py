import json

import pytest

from scripts.calibrate_jev_review_policy import calibrate_policy
from scripts.run_jev_review_comparison import FIXTURE_PATH, prepare_tasks


def _comparison(tmp_path):
    fixture = tmp_path / "fixture.json"
    document = json.loads(FIXTURE_PATH.read_text())
    document["cases"] = document["cases"][:1]
    fixture.write_text(json.dumps(document), encoding="utf-8")
    tasks, requests = prepare_tasks(fixture_path=fixture, repeats=1)
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({"model": "jev-1.14.0", "tasks": tasks}), encoding="utf-8")
    (source / "requests.jsonl").write_text("".join(json.dumps(row) + "\n" for row in requests), encoding="utf-8")
    return source


def test_compatibility_command_replays_model_dispositions(tmp_path, monkeypatch):
    monkeypatch.setattr("jev_adapter.urllib.request.urlopen", lambda *_a, **_kw: pytest.fail("replay called network"))
    report = calibrate_policy(_comparison(tmp_path), tmp_path / "report")
    assert report["mode"] == "replay"
    assert report["decision_source"] == "jev_model"
    assert report["network_calls"] == 0
    assert report["error_count"] == 2
    assert report["successful_decision_count"] == 0
    assert "threshold_selected" not in report
    assert not (tmp_path / "report" / "threshold_grid.csv").exists()


@pytest.mark.parametrize("settings", [
    {"human_labels": "labels.csv"}, {"thresholds": [0.1, 0.7]},
    {"max_unsafe_exposure_rate": 0.0}, {"ai_disclosure": "unknown"},
    {"fixture_path": "fixtures.json"},
])
def test_model_disposition_entry_rejects_local_selection_options(tmp_path, settings):
    with pytest.raises(ValueError, match="Jev Q7 determines disposition"):
        calibrate_policy(tmp_path / "source", tmp_path / "output", **settings)
    assert not (tmp_path / "output").exists()
