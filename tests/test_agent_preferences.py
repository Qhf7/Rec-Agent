from copy import deepcopy
import csv
import json
from pathlib import Path

import pytest

from agent_benchmark.dataset import build_tasks, frozen_traces
from agent_benchmark.preferences import COLUMNS, prepare_pairs, validate_annotations


def _runs(tmp_path):
    task = next(t for t in build_tasks() if t['task_id'] == 'dev_001')
    base = next(t for t in frozen_traces(build_tasks()) if t['task_id'] == task['task_id'])
    for policy in ('adaptive', 'budgeted'):
        trace = deepcopy(base)
        trace['source'], trace['policy'] = 'live_agent', policy
        trace.pop('control', None)
        trace['model_calls'] = [{'message': {'content': json.dumps(trace['final'])}}]
        if policy == 'budgeted':
            trace['final']['recommendations'][0]['exposure_reason'] += '！'
        trace['model_calls'][0]['message']['content'] = json.dumps(trace['final'])
        path = tmp_path / ('dev-' + policy) / task['task_id'] / 'trace.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(trace, ensure_ascii=False))
    return task


def _annotate(path, *, preference='A', status='human_reviewed'):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row.update(preference=preference, reviewer_id='reviewer_01', reason='人工核查商品表达与事实', status=status)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader(); writer.writerows(rows)


def test_prepare_is_blinded_deterministic_and_unlabeled(tmp_path):
    _runs(tmp_path / 'runs')
    one = prepare_pairs(tmp_path / 'runs', tmp_path / 'one')
    two = prepare_pairs(tmp_path / 'runs', tmp_path / 'two')
    assert one['pair_count'] == 1 and one['split'] == 'dev'
    assert (tmp_path / 'one/blind_pairs.jsonl').read_bytes() == (tmp_path / 'two/blind_pairs.jsonl').read_bytes()
    pair = json.loads((tmp_path / 'one/blind_pairs.jsonl').read_text())
    assert set(pair) == {'pair_id', 'context', 'candidate_A', 'candidate_B'}
    text = json.dumps(pair)
    assert not any(x in text for x in ['adaptive', 'budgeted', 'task_completed', 'valid_tool_calls', 'trace.json'])
    result = validate_annotations(tmp_path / 'one/annotation_template.csv', tmp_path / 'one/blind_pairs.jsonl', tmp_path / 'one/manifest.json')
    assert result['accepted'] == [] and result['pending_count'] == 1
    assert not list((tmp_path / 'one').glob('*chosen*'))


def test_human_label_audited_and_tie_excluded(tmp_path):
    _runs(tmp_path / 'runs'); prepare_pairs(tmp_path / 'runs', tmp_path / 'pairs')
    root = tmp_path / 'pairs'
    _annotate(root / 'annotation_template.csv')
    result = validate_annotations(root / 'annotation_template.csv', root / 'blind_pairs.jsonl', root / 'manifest.json')
    assert result['accepted_count'] == 1 and result['accepted'][0]['label_source'] == 'human_reviewed'
    assert result['accepted'][0]['chosen'] != result['accepted'][0]['rejected']
    _annotate(root / 'annotation_template.csv', preference='tie')
    result = validate_annotations(root / 'annotation_template.csv', root / 'blind_pairs.jsonl', root / 'manifest.json')
    assert result['accepted'] == [] and result['tie_count'] == 1


def test_rejects_automatic_label_provenance(tmp_path):
    _runs(tmp_path / 'runs'); prepare_pairs(tmp_path / 'runs', tmp_path / 'pairs')
    root = tmp_path / 'pairs'; _annotate(root / 'annotation_template.csv', status='jev_reviewed')
    with pytest.raises(ValueError, match='human_reviewed'):
        validate_annotations(root / 'annotation_template.csv', root / 'blind_pairs.jsonl', root / 'manifest.json')


def test_final_must_occur_in_recorded_model_response(tmp_path):
    task = _runs(tmp_path / 'runs')
    path = tmp_path / 'runs/dev-adaptive' / task['task_id'] / 'trace.json'
    trace = json.loads(path.read_text())
    trace['final']['recommendations'][0]['exposure_reason'] += '！'
    path.write_text(json.dumps(trace))
    with pytest.raises(ValueError, match='recorded model responses'):
        prepare_pairs(tmp_path / 'runs', tmp_path / 'pairs')


def test_rejects_holdout_trace_in_development_folder(tmp_path):
    task = _runs(tmp_path / 'runs')
    path = tmp_path / 'runs/dev-adaptive' / task['task_id'] / 'trace.json'
    trace = json.loads(path.read_text()); trace['task_id'] = 'holdout_001'; path.write_text(json.dumps(trace))
    with pytest.raises(ValueError, match='holdout'):
        prepare_pairs(tmp_path / 'runs', tmp_path / 'pairs')


@pytest.mark.parametrize('target', ['trace', 'pair'])
def test_hash_drift_rejected(tmp_path, target):
    task = _runs(tmp_path / 'runs'); prepare_pairs(tmp_path / 'runs', tmp_path / 'pairs')
    root = tmp_path / 'pairs'
    path = (tmp_path / 'runs/dev-adaptive' / task['task_id'] / 'trace.json') if target == 'trace' else root / 'blind_pairs.jsonl'
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='hash drift'):
        validate_annotations(root / 'annotation_template.csv', root / 'blind_pairs.jsonl', root / 'manifest.json')
