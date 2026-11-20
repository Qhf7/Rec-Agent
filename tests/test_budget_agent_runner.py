import json
from copy import deepcopy

import pytest

from agent_benchmark.runner import run_task
from agent_benchmark.tools import ToolExecutor, tool_schemas
from canonical_data import load_canonical_items


TASK = {"task_id": "dev_test", "user_id": "u_0199", "scenario": "warm",
        "requirements": ["profile", "behavior", "history", "session", "item"], "max_tool_calls": 12}


def response(*, calls=None, content=None, usage=True, reasoning=None):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [{"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}} for i, (name, arguments) in enumerate(calls)]
    if reasoning:
        message["reasoning_content"] = reasoning
    result = {"choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}]}
    if usage:
        result["usage"] = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "prompt_tokens_details": {"cached_tokens": 25}}
    return result


class FakeClient:
    model = "test-model"
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []
    def complete(self, payload):
        self.payloads.append(deepcopy(payload))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def empty_final(uid="u_0199"):
    return json.dumps({"user_id": uid, "recommendations": [], "agent_version": "rec-agent-v2"})


def item_final(item):
    return json.dumps({"user_id": TASK["user_id"], "agent_version": "rec-agent-v2", "recommendations": [{"item_id": item["item_id"], "title": item["title"],
        "exposure_reason": "清洁随手抽", "generated_reason": "清洁随手抽", "evidence_fields": ["items.title", "items.category_l3"]}]}, ensure_ascii=False)


def test_multiple_tool_calls_usage_and_real_training_messages(tmp_path):
    item = next(i for i in load_canonical_items().values() if i["stock"] > 0)
    client = FakeClient([response(calls=[("get_user_profile", {"user_id": TASK["user_id"]}), ("get_item", {"item_id": item["item_id"]})], reasoning="do not retain hidden thoughts"), response(content=item_final(item))])
    trace = run_task(TASK, "adaptive", client=client, output_dir=tmp_path)
    assert len(trace["calls"]) == 2
    assert trace["final"]["recommendations"][0]["item_id"] == item["item_id"]
    assert trace["usage"]["total_tokens"] == 300
    assert trace["usage"]["cached_tokens"] == 50
    assert trace["training_eligible"]
    assert [m["role"] for m in trace["training_messages"]] == ["system", "user", "assistant", "tool", "tool", "assistant"]
    assert "reasoning_content" not in json.dumps(trace)
    assert (tmp_path / "trace.json").is_file()
    assert all(p["max_tokens"] == 4096 for p in client.payloads)
    assert "response_format" not in client.payloads[0]


def test_invalid_types_are_recorded_without_execution():
    executor = ToolExecutor(TASK)
    client = FakeClient([response(calls=[("search_items", {"limit": "3"})]), response(content=empty_final())])
    trace = run_task(TASK, "adaptive", client=client, executor=executor)
    assert len(trace["calls"]) == 1
    assert trace["calls"][0]["valid_parameters"] is False
    assert trace["calls"][0]["error"] == "invalid_tool_parameters"
    assert trace["final"] is not None


def test_empty_search_can_recover_with_another_search():
    task = {**TASK, "scenario": "empty_search"}
    client = FakeClient([response(calls=[("search_items", {"query": "抽纸", "limit": 3})]),
                         response(calls=[("search_items", {"limit": 3})]), response(content=empty_final())])
    trace = run_task(task, "adaptive", client=client)
    assert trace["calls"][0]["result"] == []
    assert trace["calls"][1]["result"]
    assert len(trace["model_calls"]) == 3


def test_tool_budget_disables_tools_for_final_generation():
    client = FakeClient([response(calls=[("get_user_profile", {"user_id": TASK["user_id"]})]), response(content=empty_final())])
    trace = run_task(TASK, "budgeted", client=client, max_tool_calls=1, max_tokens=50000)
    assert len(trace["calls"]) == 1
    assert "tools" not in client.payloads[1]
    assert client.payloads[1]["response_format"] == {"type": "json_object"}
    assert trace["budget_exceeded"] is False


def test_multiple_calls_cannot_overrun_tool_budget():
    client = FakeClient([response(calls=[("get_user_profile", {"user_id": TASK["user_id"]}), ("get_user_behavior", {"user_id": TASK["user_id"]})])])
    trace = run_task(TASK, "budgeted", client=client, max_tool_calls=1, max_tokens=50000)
    assert len(trace["calls"]) == 1
    assert len(trace["model_calls"]) == 1
    assert trace["budget_exceeded"] is True
    assert trace["stop_reason"] == "tool_budget_exhausted"


def test_max_tokens_limits_each_response_without_cumulative_gate():
    client = FakeClient([response(content=empty_final())])
    trace = run_task(TASK, "budgeted", client=client, max_tokens=512)
    assert client.payloads[0]["max_tokens"] == 512
    assert trace["budgets"]["max_tokens"] is None
    assert trace["budgets"]["max_response_tokens"] == 512
    assert not trace["budget_exceeded"]


def test_unknown_reported_usage_remains_unknown_but_does_not_stop_calls():
    client = FakeClient([response(calls=[("get_user_profile", {"user_id": TASK["user_id"]})], usage=False), response(content=empty_final())])
    trace = run_task(TASK, "budgeted", client=client)
    assert trace["usage"]["status"] == "unknown"
    assert trace["usage"]["total_tokens"] is None
    assert trace["final"] is not None
    assert not trace["budget_exceeded"]
    assert len(client.payloads) == 2


def test_reported_usage_above_twenty_four_thousand_does_not_stop_tools():
    answer = response(calls=[("get_user_profile", {"user_id": TASK["user_id"]})])
    answer["usage"] = {"prompt_tokens": 60000, "completion_tokens": 1, "total_tokens": 60001}
    client = FakeClient([answer, response(content=empty_final())])
    trace = run_task(TASK, "budgeted", client=client)
    assert trace["usage"]["total_tokens"] == 60151
    assert trace["budget_exceeded"] is False
    assert trace["final"] is not None
    assert len(trace["calls"]) == 1


def test_provider_errors_are_safe_and_no_exception_bodies_are_saved():
    client = FakeClient([RuntimeError("secret provider response sk-never-save")])
    trace = run_task(TASK, "adaptive", client=client)
    assert trace["error"] == "model_call_failed"
    assert "sk-never-save" not in json.dumps(trace)


def test_fixed_policy_uses_same_model_but_does_not_forge_training_tools():
    client = FakeClient([response(content=empty_final())])
    trace = run_task(TASK, "fixed", client=client)
    assert [c["name"] for c in trace["calls"]] == ["get_user_profile", "get_user_behavior", "get_user_recommendation_history", "get_session_context", "search_items", "get_item", "get_item", "get_item"]
    assert len(client.payloads) == 1
    assert "tools" not in client.payloads[0]
    assert trace["training_eligible"] is False
    assert all("tool_calls" not in message for message in trace["training_messages"])


def test_final_text_must_obey_existing_twenty_character_contract():
    item = next(i for i in load_canonical_items().values() if i["stock"] > 0)
    final = json.loads(item_final(item))
    final["recommendations"][0]["exposure_reason"] = "24包家庭装"
    final["recommendations"][0]["generated_reason"] = "24包家庭装"
    client = FakeClient([response(calls=[("get_item", {"item_id": item["item_id"]})]), response(content=json.dumps(final))])
    trace = run_task(TASK, "adaptive", client=client, max_model_calls=2)
    assert trace["final"] is None
    assert trace["stop_reason"] == "model_round_limit"


def test_round_limit_cannot_exceed_eight():
    with pytest.raises(ValueError):
        run_task(TASK, client=FakeClient([]), max_model_calls=9)


def test_unknown_user_fixed_stops_context_tools_after_profile():
    uid = "u_9999"
    task = {**TASK, "user_id": uid, "scenario": "unknown", "requirements": ["profile"]}
    client = FakeClient([response(content=empty_final(uid))])
    trace = run_task(task, "fixed", client=client)
    assert len(trace["calls"]) == 1
    assert trace["final"]["recommendations"] == []
    from agent_benchmark.metrics import evaluate_trace
    assert evaluate_trace(task, trace)["task_completed"]


def test_time_limit_stops_after_slow_provider_without_executing_tools():
    times = [0.0]
    def clock():
        return times[0]
    class SlowClient(FakeClient):
        def complete(self, payload):
            times[0] = 11.0
            return super().complete(payload)
    client = SlowClient([response(calls=[("get_user_profile", {"user_id": TASK["user_id"]})])])
    trace = run_task(TASK, "budgeted", client=client, clock=clock, max_seconds=10, max_tokens=50000)
    assert trace["stop_reason"] == "time_budget_exhausted"
    assert trace["duration_seconds"] == 11
    assert trace["calls"] == []


@pytest.mark.parametrize("arguments", [{"limit": True}, {"limit": 51}, {"query": "x" * 121}, {"nonsense": 1}])
def test_schema_invalid_search_parameters_never_execute(arguments):
    client = FakeClient([response(calls=[("search_items", arguments)]), response(content=empty_final())])
    trace = run_task(TASK, "adaptive", client=client)
    assert trace["calls"][0]["valid_parameters"] is False
    assert trace["calls"][0]["error"] == "invalid_tool_parameters"


def test_empty_recommendations_do_not_make_known_user_task_succeed():
    client = FakeClient([response(content=empty_final())])
    trace = run_task(TASK, "adaptive", client=client)
    assert trace["final"] is not None
    from agent_benchmark.metrics import evaluate_trace
    assert evaluate_trace(TASK, trace)["task_completed"] is False
    assert trace["training_eligible"] is True  # Independent quality filter is still required.


def test_budgeted_projects_model_context_without_mutating_executor_facts():
    executor = ToolExecutor(TASK)
    client = FakeClient([response(calls=[("get_user_profile", {"user_id": TASK["user_id"]}), ("get_user_recommendation_history", {"user_id": TASK["user_id"]}), ("search_items", {"limit": 6})]), response(content=empty_final())])
    trace = run_task(TASK, "budgeted", client=client, executor=executor, max_tokens=50000)
    originals = {c["name"]: c for c in executor.calls}
    assert len(originals["search_items"]["result"]) == 6
    assert "events" in originals["get_user_recommendation_history"]["result"]
    projected = {c["name"]: c["model_observation"] for c in trace["calls"]}
    assert len(projected["search_items"]["result"]) == 4
    assert projected["search_items"]["observation_metadata"]["returned_count"] == 6
    assert projected["search_items"]["observation_metadata"]["truncated"] is True
    assert "events" not in projected["get_user_recommendation_history"]["result"]
    assert "age" not in projected["get_user_profile"]["result"]
    for shown, original in zip(projected["search_items"]["result"], originals["search_items"]["result"]):
        assert all(original[field] == value for field, value in shown.items())
    assert "observation_metadata" in client.payloads[1]["messages"][-2]["content"]


def test_adaptive_keeps_full_observations_for_compression_ablation():
    client = FakeClient([response(calls=[("search_items", {"limit": 6})]), response(content=empty_final())])
    trace = run_task(TASK, "adaptive", client=client)
    assert len(trace["calls"][0]["model_observation"]["result"]) == 6
    assert "observation_metadata" not in trace["calls"][0]["model_observation"]


def test_budgeted_finalizes_when_required_facts_are_observed():
    item = next(i for i in load_canonical_items().values() if i["stock"] > 0)
    client = FakeClient([response(calls=[("get_user_profile", {"user_id": TASK["user_id"]}),
        ("get_user_behavior", {"user_id": TASK["user_id"]}),
        ("get_user_recommendation_history", {"user_id": TASK["user_id"]}),
        ("get_session_context", {}), ("get_item", {"item_id": item["item_id"]})]), response(content=item_final(item))])
    trace = run_task(TASK, "budgeted", client=client, max_tokens=50000)
    assert trace["final"] is not None
    assert "tools" not in client.payloads[1]
    assert trace["model_calls"][1]["final_only"] is True
    assert trace["calls"][-1]["model_observation"]["result"]["functions"] == item["functions"]


def test_reported_token_totals_do_not_change_planning_availability():
    first = response(calls=[("get_user_profile", {"user_id": TASK["user_id"]})])
    first["usage"] = {"prompt_tokens": 60000, "completion_tokens": 1000, "total_tokens": 61000}
    client = FakeClient([first, response(content=empty_final())])
    trace = run_task(TASK, "budgeted", client=client)
    assert trace["final"] is not None
    assert trace["model_calls"][1]["final_only"] is False
    assert "tools" in client.payloads[1]
    assert not trace["budget_exceeded"]
    assert all("reported_tokens_remaining" not in json.dumps(payload) for payload in client.payloads)


def test_final_repair_feedback_names_unobserved_items_and_bad_evidence():
    first, second = [i for i in load_canonical_items().values() if i["stock"] > 0][:2]
    invalid = json.loads(item_final(first))
    invalid["recommendations"][0]["evidence_fields"] = ["items.item_id", "items.stock"]
    invalid["recommendations"].append(json.loads(item_final(second))["recommendations"][0])
    client = FakeClient([response(calls=[("get_item", {"item_id": first["item_id"]})]),
                         response(content=json.dumps(invalid)), response(content=item_final(first))])
    trace = run_task(TASK, "adaptive", client=client)
    assert trace["final"] is not None
    errors = trace["validation_failures"][0]
    assert any(e["code"] == "item_details_not_observed" and e["item_id"] == second["item_id"] for e in errors)
    assert any(e["code"] == "invalid_evidence" and e["invalid_paths"] == ["items.item_id", "items.stock"] for e in errors)
    metadata = trace["calls"][0]["model_observation"]["evidence_allowlist"]
    assert "items.title" in metadata
    assert "items.item_id" not in metadata
    assert "items.stock" not in metadata
    assert "validation_errors" in json.dumps(client.payloads[2])


def test_search_results_without_get_item_cannot_be_final_recommendations():
    item = next(i for i in load_canonical_items().values() if i["stock"] > 0)
    client = FakeClient([response(calls=[("search_items", {"query": item["title"], "limit": 1})]), response(content=item_final(item))])
    trace = run_task(TASK, "adaptive", client=client, max_model_calls=2)
    assert trace["final"] is None
    assert trace["validation_failures"][0][0]["code"] == "item_details_not_observed"


def test_compaction_can_be_disabled_under_the_same_budgeted_policy():
    client = FakeClient([response(calls=[("search_items", {"limit": 6})]), response(content=empty_final())])
    trace = run_task(TASK, "budgeted", client=client, compact_observations=False)
    assert len(trace["calls"][0]["model_observation"]["result"]) == 6
    assert trace["runtime_settings"]["compact_observations"] is False
    assert trace["runtime_settings"]["early_finish"] is True
    assert trace["budgets"]["max_tool_calls"] == TASK["max_tool_calls"]


def test_early_finish_can_be_disabled_under_the_same_budgeted_policy():
    task = {**TASK, "user_id": "u_9999", "requirements": ["profile"]}
    client = FakeClient([response(calls=[("get_user_profile", {"user_id": task["user_id"]})]), response(content=empty_final(task["user_id"]))])
    trace = run_task(task, "budgeted", client=client, early_finish=False)
    assert trace["model_calls"][1]["final_only"] is False
    assert "tools" in client.payloads[1]
    assert trace["runtime_settings"]["early_finish"] is False
    assert trace["runtime_settings"]["compact_observations"] is True


@pytest.mark.parametrize("policy", ["fixed", "adaptive", "budgeted"])
def test_all_policies_share_task_tool_limit_by_default(policy):
    client = FakeClient([response(content=empty_final())])
    trace = run_task(TASK, policy, client=client)
    assert trace["budgets"]["max_tool_calls"] == 12
    assert trace["runtime_settings"]["runner_version"] == "matched-tool-budget-v2"
