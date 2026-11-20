from copy import deepcopy
import hashlib
import json

import pytest

from agent_benchmark.dataset import build_tasks, freeze_dataset, frozen_traces
from agent_benchmark.metrics import evaluate_trace
from agent_benchmark.tools import ToolExecutor, tool_schemas, validate_arguments


def test_deterministic_user_disjoint_dataset():
    tasks = build_tasks()
    assert tasks == build_tasks()
    assert len(tasks) == 20
    dev = {t['user_id'] for t in tasks if t['split'] == 'dev'}
    holdout = {t['user_id'] for t in tasks if t['split'] == 'holdout'}
    assert len(dev) == 12 and len(holdout) == 8 and not dev & holdout
    assert {t['scenario'] for t in tasks} == {'warm', 'cold_start', 'unknown', 'empty_search', 'tool_timeout', 'missing_item_fields'}


@pytest.mark.parametrize('name,args', [
    ('bad_tool', {}), ('get_user_profile', {'user_id': 'item_0001'}),
    ('get_item', {'item_id': 'i_0001', 'extra': True}),
    ('search_items', {'limit': '3'}), ('search_items', {'limit': True}),
    ('search_items', {'limit': 0}), ('search_items', {'limit': 51}),
    ('search_items', {'category_l1': 'imaginary'}),
    ('search_items', {'query': 'x' * 121}), ('search_items', {'in_stock_only': 1}),
    ('get_user_recommendation_history', {'user_id': 'u_0001', 'days': 0}),
    ('get_user_recommendation_history', {'user_id': 'u_0001', 'limit': 101}),
    ('get_promo', {'as_of': '2027-01-01'}), ('get_session_context', {'x': 1}),
])
def test_invalid_arguments(name, args):
    with pytest.raises(ValueError):
        validate_arguments(name, args)


def test_tools_parameters_and_task_user_boundary():
    assert len(tool_schemas()) == 7
    for schema in tool_schemas():
        assert schema['function']['parameters']['additionalProperties'] is False
    task = build_tasks()[0]
    response = ToolExecutor(task).call('get_user_profile', {'user_id': 'u_9999'})
    assert not response['ok']
    validate_arguments('get_user_recommendation_history', {'user_id': task['user_id'], 'limit': 0, 'days': 365})


@pytest.mark.parametrize('scenario', ['empty_search', 'tool_timeout', 'missing_item_fields'])
def test_faults_inject_once_without_mutating_canonical(scenario):
    task = next(t for t in build_tasks() if t['scenario'] == scenario)
    executor = ToolExecutor(task)
    name, args = ('get_item', {'item_id': 'i_0001'}) if scenario == 'missing_item_fields' else ('search_items', {'limit': 1})
    one = executor.call(name, args)
    two = executor.call(name, args)
    assert len(executor.faults) == 1
    assert two['ok'] and two['result']
    if scenario == 'missing_item_fields':
        assert 'functions' not in one['result'] and 'functions' in two['result']
    elif scenario == 'empty_search':
        assert one['result'] == []
    else:
        assert not one['ok'] and one['error']['type'] == 'TimeoutError'


def test_controls_and_independent_metrics():
    tasks = build_tasks()
    by_id = {t['task_id']: t for t in tasks}
    traces = frozen_traces(tasks)
    assert len(traces) >= 12 and all(t['source'] == 'constructed_trace' for t in traces)
    for trace in traces:
        result = evaluate_trace(by_id[trace['task_id']], trace)
        expected = trace['control'].startswith('success_') or trace['control'] == 'invalid_parameter_then_recovery'
        assert result['task_completed'] is expected, (trace['control'], result)
    invalid = next(t for t in traces if t['control'] == 'invalid_parameter_then_recovery')
    result = evaluate_trace(by_id[invalid['task_id']], invalid)
    assert result['valid_tool_calls'] == result['attempted_tool_calls'] - 1


def test_final_fields_cannot_substitute_observations():
    tasks = build_tasks()
    trace = frozen_traces(tasks)[0]
    trace['calls'] = []
    result = evaluate_trace(next(t for t in tasks if t['task_id'] == trace['task_id']), trace)
    assert result['fact_coverage'] == 0 and not result['task_completed']


def test_fabricated_history_statistics_are_not_covered():
    tasks = build_tasks()
    trace = frozen_traces(tasks)[0]
    task = next(t for t in tasks if t['task_id'] == trace['task_id'])
    history = next(c for c in trace['calls'] if c['name'] == 'get_user_recommendation_history')
    history['result']['event_count'] += 1000
    result = evaluate_trace(task, trace)
    assert result['fact_coverage'] == 0.8 and not result['task_completed']


def test_missing_detail_evidence_rejected_and_reason_boundaries():
    tasks = build_tasks()
    task = next(t for t in tasks if t['scenario'] == 'missing_item_fields')
    trace = next(t for t in frozen_traces(tasks) if t['task_id'] == task['task_id'])
    details = [c for c in trace['calls'] if c['name'] == 'get_item']
    trace['calls'].remove(details[-1])
    assert not evaluate_trace(task, trace)['final_valid']
    trace = frozen_traces(tasks)[0]
    task = next(t for t in tasks if t['task_id'] == trace['task_id'])
    trace['final']['recommendations'][0]['exposure_reason'] = '整箱24包'
    assert not evaluate_trace(task, trace)['final_valid']


def test_budget_overrun_is_recorded():
    task = deepcopy(build_tasks()[0])
    task['max_tool_calls'] = 1
    executor = ToolExecutor(task)
    assert executor.call('get_session_context', {})['ok']
    assert not executor.call('get_session_context', {})['ok']
    assert executor.budget_exceeded and len(executor.calls) == 2


def test_freeze_content_hashes_reproducible(tmp_path):
    first = freeze_dataset(tmp_path / 'one')
    second = freeze_dataset(tmp_path / 'two')
    assert first == second
    for name, artifact in first['artifacts'].items():
        data = (tmp_path / 'one' / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == artifact['sha256']
        assert len(json.loads(data)) == artifact['count']
