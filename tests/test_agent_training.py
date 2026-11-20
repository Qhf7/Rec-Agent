"""Pure data/protocol tests. Unit fixtures are never real training artifacts."""
from copy import deepcopy
import json
import pytest
from agent_benchmark import training


class TinyTokenizer:
    eos_token_id = 999

    def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=False):
        result = []
        for message in messages:
            result += [101 if message['role'] == 'assistant' else 102]
            result += [ord(c) for c in message['content']]
            result += [self.eos_token_id]
        if add_generation_prompt:
            result += [101]
        return result


@pytest.fixture
def contract_fixture(monkeypatch):
    # Constructed unit data only; production prepare never reads unit fixtures.
    monkeypatch.setattr('agent_benchmark.metrics.evaluate_trace', lambda task, trace: {'task_completed': trace.get('test_verifier_pass', True)})
    tasks = [{'task_id': 'dev_test', 'split': 'dev', 'user_id': 'u_0001'},
             {'task_id': 'holdout_test', 'split': 'holdout', 'user_id': 'u_0002'}]
    action = {'role': 'assistant', 'content': None, 'reasoning_content': 'SECRET HIDDEN THOUGHT',
              'tool_calls': [{'id': 'a', 'type': 'function', 'function': {'name': 'get_user_profile', 'arguments': '{"user_id":"u_0001"}'}}]}
    final = {'user_id': 'u_0001', 'recommendations': []}
    final_message = {'role': 'assistant', 'content': json.dumps(final)}
    trace = {'task_id': 'dev_test', 'user_id': 'u_0001', 'source': 'live_agent',
             'calls': [{'name': 'get_user_profile', 'arguments': {'user_id': 'u_0001'}, 'result': {'found': False}}],
             'final': final, 'model_calls': [{'message': action}, {'message': final_message}],
             'training_messages': [{'role': 'system', 'content': 'Test contract'}, {'role': 'user', 'content': 'Read profile'}, action,
                                   {'role': 'tool', 'tool_call_id': 'a', 'content': '{"ok":true,"result":{"found":false}}'}, final_message]}
    return tasks, trace


def test_targets_only_mask_preserves_chat_and_eos():
    record = {'messages': [{'role': 'user', 'content': 'Question'}], 'target': 'ACTION'}
    encoded = training.encode_record(record, TinyTokenizer(), 50)
    target_length = len('ACTION') + 1
    assert encoded['labels'][:-target_length] == [-100] * (len(encoded['input_ids']) - target_length)
    assert encoded['labels'][-target_length:] == [ord(c) for c in 'ACTION'] + [999]
    assert encoded['input_ids'][-1] == 999
    assert len(encoded['attention_mask']) == len(encoded['input_ids']) == len(encoded['labels'])
    assert not encoded['prompt_truncated']


def test_target_never_silently_truncated():
    with pytest.raises(ValueError, match='target exceeds'):
        training.encode_record({'messages': [{'role': 'user', 'content': 'x'}], 'target': 'a' * 25}, TinyTokenizer(), 20)
    encoded = training.encode_record({'messages': [{'role': 'user', 'content': 'x' * 100}], 'target': 'ok'}, TinyTokenizer(), 20)
    assert encoded['prompt_truncated']
    assert encoded['labels'][-3:] == [ord('o'), ord('k'), 999]


def test_build_records_filters_holdout_constructed_and_failed(contract_fixture):
    tasks, live = contract_fixture
    holdout = deepcopy(live)
    holdout.update(task_id='holdout_test', user_id='u_0002')
    constructed = deepcopy(live)
    constructed['source'] = 'constructed_trace'
    failed = deepcopy(live)
    failed['test_verifier_pass'] = False
    no_model = deepcopy(live)
    no_model['model_calls'] = 0
    records = training.build_training_records([live, holdout, constructed, failed, no_model, live], tasks)
    assert len(records) == 2
    assert {row['task_id'] for row in records} == {'dev_test'}
    assert len({row['source_trace_sha256'] for row in records}) == 1
    assert all(row['verification']['verifier'] == 'agent_benchmark.metrics.evaluate_trace' for row in records)
    assert all('SECRET' not in json.dumps(row) for row in records)


def test_native_tool_conversion_and_hidden_reasoning_removal(contract_fixture):
    tasks, trace = contract_fixture
    messages = training.export_trace_messages(trace, tasks[0])
    action = json.loads(messages[2]['content'])
    assert action == {'tool_calls': [{'name': 'get_user_profile', 'arguments': {'user_id': 'u_0001'}}]}
    assert messages[3]['role'] == 'user'
    observation = json.loads(messages[3]['content'])
    assert observation['tool'] == 'get_user_profile'
    assert observation['observation']['ok'] is True
    assert json.loads(messages[-1]['content']) == {'final': trace['final']}
    assert 'SECRET' not in json.dumps(messages)


def test_rejects_transcript_executed_call_mismatch(contract_fixture):
    tasks, trace = contract_fixture
    trace['calls'][0]['arguments']['user_id'] = 'u_0022'
    assert training.build_training_records([trace], tasks) == []


def test_rejects_missing_transcript_and_self_reported_success(contract_fixture):
    tasks, trace = contract_fixture
    trace.pop('training_messages')
    trace.update(verified_success=True, verification={'success': True})
    assert training.build_training_records([trace], tasks) == []


def test_group_split_has_no_task_or_user_leakage():
    rows = [{'task_id': f'task_{i}', 'user_id': f'user_{i // 2}', 'target': str(j)} for i in range(8) for j in range(3)]
    first, second = training.split_training_records(rows, validation_fraction=.25)
    assert first and second
    assert not {r['user_id'] for r in first} & {r['user_id'] for r in second}
    assert not {r['task_id'] for r in first} & {r['task_id'] for r in second}
    assert (first, second) == training.split_training_records(rows, validation_fraction=.25)


def test_registry_rejects_holdout_user_overlap(contract_fixture):
    tasks, trace = contract_fixture
    tasks[1]['user_id'] = tasks[0]['user_id']
    with pytest.raises(ValueError, match='overlap'):
        training.build_training_records([trace], tasks)


def test_action_parser_rejects_untrusted_wrappers_and_wrong_parameters():
    action = '{"tool_calls":[{"name":"get_user_profile","arguments":{"user_id":"u_0001"}}]}'
    assert training.parse_action(action, {'user_id': 'u_0001'})['tool_calls'][0]['name'] == 'get_user_profile'
    fence = chr(96) * 3
    invalids = (fence + 'json\n' + action + '\n' + fence, action + '\nmore', '{"final":{},"thought":"x"}',
                action.replace('u_0001', 'u_0002'), '{"tool_calls":[]}')
    for invalid in invalids:
        with pytest.raises((ValueError, TypeError, KeyError)):
            training.parse_action(invalid, {'user_id': 'u_0001'})


def test_constructed_controls_do_not_enter_real_training():
    from agent_benchmark.dataset import build_tasks, frozen_traces
    tasks = build_tasks()
    assert training.build_training_records(frozen_traces(tasks), tasks) == []


def test_holdout_diagnostics_are_separate_unseen_users():
    from agent_benchmark.dataset import build_tasks
    tasks = build_tasks()
    cases = training.build_step_evaluation_cases(tasks)
    assert len(cases) == 8
    assert len({case['user_id'] for case in cases}) == 8
    assert not {case['user_id'] for case in cases} & {t['user_id'] for t in tasks if t['split'] == 'dev'}
    assert all(case['source'] == 'constructed_holdout_step_state_diagnostic_only' for case in cases)
    assert all(training.parse_action(case['target']) == case['expected_action'] for case in cases)


def test_rejects_unrecorded_model_action(contract_fixture):
    tasks, trace = contract_fixture
    trace['model_calls'] = trace['model_calls'][-1:]
    assert training.build_training_records([trace], tasks) == []


def test_rejects_modified_tool_observation(contract_fixture):
    tasks, trace = contract_fixture
    trace['training_messages'][3]['content'] = '{"ok":true,"result":{"found":true,"invented":"fact"}}'
    assert training.build_training_records([trace], tasks) == []


def test_recorded_model_observation_must_match_actual_input(contract_fixture):
    tasks, trace = contract_fixture
    trace['calls'][0]['model_observation'] = {'ok': True, 'result': {'found': True}}
    assert training.build_training_records([trace], tasks) == []


def test_prepare_refuses_constructed_fallback(tmp_path):
    from agent_benchmark.dataset import build_tasks, frozen_traces
    tasks = build_tasks()
    with pytest.raises(ValueError, match='refusing synthetic fallback'):
        training.prepare_data(frozen_traces(tasks), tasks, tmp_path)


def test_local_client_translates_exact_actions_without_repair(monkeypatch):
    client = training.LocalActionClient.__new__(training.LocalActionClient)
    client._model, client.tokenizer = object(), object()
    client.max_input_tokens, client.max_new_tokens, client.predictions = 2048, 128, []
    predicted = {'action': {'tool_calls': [{'name': 'get_session_context', 'arguments': {}}]}, 'text': 'raw',
                 'input_tokens': 10, 'output_tokens': 5}
    monkeypatch.setattr(training, 'predict_action', lambda *args, **kwargs: deepcopy(predicted))
    response = client.complete({'messages': [], 'max_tokens': 80})
    message = response['choices'][0]['message']
    assert message['tool_calls'][0]['function'] == {'name': 'get_session_context', 'arguments': '{}'}
    assert response['usage']['total_tokens'] == 15
    predicted.update(action=None, text='INVALID JSON')
    response = client.complete({'messages': []})
    assert response['choices'][0]['message']['content'] == 'INVALID JSON'
    assert not response['choices'][0]['message'].get('tool_calls')


def test_selected_target_loss_matches_full_causal_cross_entropy():
    torch = pytest.importorskip('torch')
    from types import SimpleNamespace
    class Decoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = torch.nn.Embedding(12, 4)
        def forward(self, input_ids, attention_mask, use_cache, return_dict):
            return SimpleNamespace(last_hidden_state=self.embedding(input_ids))
    class ToyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = Decoder()
            self.head = torch.nn.Linear(4, 12)
        def get_output_embeddings(self):
            return self.head
    torch.manual_seed(1)
    model = ToyModel()
    batch = {'input_ids': torch.tensor([[1, 2, 3, 4, 5]]), 'attention_mask': torch.ones((1, 5), dtype=torch.long),
             'labels': torch.tensor([[-100, -100, 3, 4, 5]])}
    full_logits = model.head(model.model(**{k:v for k,v in batch.items() if k!='labels'}, use_cache=False, return_dict=True).last_hidden_state)
    expected = torch.nn.functional.cross_entropy(full_logits[:, :-1].reshape(-1, 12), batch['labels'][:, 1:].reshape(-1), ignore_index=-100)
    actual = training._target_loss(model, batch)
    assert torch.allclose(expected, actual, atol=1e-7)
    actual.backward()
    assert model.model.embedding.weight.grad is not None
