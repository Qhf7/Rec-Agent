from copy import deepcopy
import pytest

from agent_benchmark.dataset import build_tasks, frozen_traces
from agent_benchmark.judges import judge_input, parse_choices, percentile, questions, reference, usage_of


def test_evaluators_share_questions_and_never_receive_reference_labels():
    tasks = build_tasks()
    trace = frozen_traces(tasks)[0]
    state = judge_input(tasks[0], trace)
    assert state["questions"] == questions()
    assert set(questions()) == {"task_completed", "tool_parameters", "fact_coverage"}
    assert "control" not in state["trace"] and "source" not in state["trace"]
    assert "reference" not in state and "task_completed" not in state["trace"]
    assert all("valid_parameters" not in c for c in state["trace"]["calls"])


def test_provider_usage_aliases_preserve_missing_values():
    assert usage_of({})["total_tokens"] is None
    jev = usage_of({"usage": {"input_tokens": 200, "output_tokens": 30}})
    assert (jev["prompt_tokens"], jev["completion_tokens"], jev["total_tokens"]) == (200, 30, 230)
    llm = usage_of({"usage": {"prompt_tokens": 80, "completion_tokens": 2, "total_tokens": 82}})
    assert llm["total_tokens"] == 82 and llm["cached_tokens"] is None


def test_strict_choices_and_confidence():
    valid = {"answers": {k: {"choice": next(iter(v["criteria"])), "confidence": .8} for k, v in questions().items()}}
    assert set(parse_choices(valid)) == set(questions())
    bad = deepcopy(valid)
    bad["answers"]["tool_parameters"]["choice"] = "yes"
    with pytest.raises(ValueError):
        parse_choices(bad)
    valid["answers"]["task_completed"]["confidence"] = True
    with pytest.raises(ValueError):
        parse_choices(valid)


def test_references_include_failed_and_recovered_attempts():
    tasks = build_tasks()
    by = {t["task_id"]: t for t in tasks}
    traces = frozen_traces(tasks)
    refs = [reference(by[t["task_id"]], t) for t in traces]
    assert any(r["tool_parameters"] == "has_invalid" and r["task_completed"] == "yes" for r in refs)
    assert any(r["task_completed"] == "no" for r in refs)
    assert percentile([1, 2, 3, 4, 5]) == pytest.approx(4.8)
    assert percentile([]) is None
