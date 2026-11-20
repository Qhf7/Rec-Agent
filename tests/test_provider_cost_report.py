import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_benchmark.provider_report import LABELS, generate
from agent_benchmark.providers import usage_of


def test_chart_labels_use_reported_reasoning_settings():
    assert LABELS["highland_sol_requested_ultra"] == "Sol (xhigh)"
    assert "Ultra" not in " ".join(LABELS.values())
    assert "thinking on" in LABELS["kimi_k31_thinking"]


def test_usage_retains_reported_cache_write_zero():
    result = usage_of({"usage": {"prompt_tokens": 100, "completion_tokens": 30,
        "total_tokens": 130, "prompt_tokens_details": {"cache_write_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 20}}})
    assert result["input_tokens_details"]["cache_write_tokens"] == 0
    assert result["cached_tokens"] is None
    assert result["completion_tokens"] == 30


def test_report_adds_official_price_equivalents_with_separate_assumptions(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100,
             "cached_tokens": 400, "reasoning_tokens": 50, "estimated": True}
    metric = {"config": {"model": "test", "reasoning_effort": None}, "returned_reasoning_efforts": [],
        "requests": 1, "valid_answers": 1, "agreement_all_attempts": {"task_completed": 1, "tool_parameters": 1, "fact_coverage": 1},
        "prompt_tokens": {"mean_reported": 1000}, "completion_tokens": {"mean_reported": 100},
        "total_tokens": {"mean_reported": 1100}, "reasoning_tokens": {"mean_reported": 50},
        "estimated_usage_requests": 1, "p95_latency_seconds": 2, "transport_failures": 0, "parse_failures": 0}
    summary = {"schema_version": "test", "case_count": 1, "workers": 2, "repeats": 1,
               "reference_type": "programmatic", "evaluators": {"kimi_k31_thinking": metric}}
    result = {"case_id": "a", "kind": "kimi_k31_thinking", "status": "ok", "reference": {},
              "choices": {}, "latency_seconds": 2, "usage": usage, "metadata": {}, "input_sha256": "hash"}
    for name, value in (("summary.json", summary), ("manifest.json", {"source_manifest_sha256": "hash", "cases": [{}]}),
                        ("results.json", [result])):
        (source / name).write_text(json.dumps(value))
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"evaluators": {"kimi_k31_thinking": {"input_per_million": 2,
        "cached_input_per_million": .2, "output_per_million": 10, "official_model": "test"}}}))
    with patch("agent_benchmark.provider_report._figures"):
        generate(source, target, prices)
    output = json.loads((target / "costs.json").read_text())["kimi_k31_thinking"]
    assert output["cold"]["per_1000_measured_usd"] == pytest.approx(3)
    assert output["observed"]["per_1000_measured_usd"] == pytest.approx(2.28)
    assert output["cold"]["estimated_count"] == 1
