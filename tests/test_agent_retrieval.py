from copy import deepcopy
import hashlib
import json
import math

import pytest

from agent_benchmark.dataset import build_tasks
from agent_benchmark.retrieval import METHODS, PairwiseReranker, RetrievalIndex, build_query, ranking_context, ranking_metrics, run_evaluation, tokenize, weak_labels
from canonical_data import load_canonical_items, load_canonical_users


def test_chinese_bigram_and_word_frequencies():
    assert tokenize('智能手环 Smart smart') == ['智能', '能手', '手环', 'smart', 'smart']


def test_ranking_never_reads_cart_or_other_hidden_fields():
    class User(dict):
        def get(self, key, default=None):
            assert key in ('preferred_categories', 'last_search_terms')
            return super().get(key, default)
    user = User(preferred_categories=['3C数码'], last_search_terms=['智能手环'], recent_cart_item_ids=['i_0001'])
    index = RetrievalIndex(load_canonical_items())
    assert 'i_0001' not in build_query(user)
    for method in METHODS:
        assert len(index.rank(method, user)) == 10
        changed = deepcopy(user)
        changed['recent_cart_item_ids'] = ['i_0200']
        assert index.rank(method, user) == index.rank(method, changed)


def test_weak_labels_keep_stockout_and_match_complete_search_phrase():
    items = {'i_0001': {'stock': 0, 'title': '蓝牙耳机', 'category_l3': '耳机'},
             'i_0002': {'stock': 1, 'title': '蓝牙音箱', 'category_l3': '音箱'}}
    labels = weak_labels({'recent_cart_item_ids': ['i_0001', 'i_9999'], 'last_search_terms': ['蓝牙耳机']}, items)
    assert labels == {'cart': {'i_0001'}, 'search_exact': {'i_0001'}, 'union': {'i_0001'}}


def test_metric_values_and_missing_label_semantics():
    result = ranking_metrics(['a', 'x', 'b'], {'a', 'b'})
    assert result['recall_at_10'] == 1 and result['mrr_at_10'] == 1
    assert result['ndcg_at_10'] == pytest.approx((1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3)))
    assert ranking_metrics(['x'], set())['recall_at_10'] is None
    assert ranking_metrics(['a'] * 4, {'a', 'b'})['recall_at_10'] == 0.5


def test_rankers_are_deterministic_and_filter_stockouts():
    items = load_canonical_items()
    index = RetrievalIndex(items)
    user = load_canonical_users()['u_0001']
    for method in METHODS:
        result = index.rank(method, user)
        assert result == index.rank(method, user) and len(result) == len(set(result)) == 10
        assert all(items[iid]['stock'] > 0 for iid in result)
    with pytest.raises(ValueError):
        index.rank('embedding', user)
    with pytest.raises(ValueError):
        index.rank('rule', user, as_of='2026-12-01')


def test_report_split_coverage_and_nulls(tmp_path):
    tasks = build_tasks()
    report = run_evaluation(tmp_path, tasks=tasks)
    assert report['catalog_size'] == 200 and report['eligible_catalog_size'] == 185
    assert len(report['summary']) == 18 and len(report['per_task']) == 180
    unknown = [row for row in report['per_task'] if not row['known_user']]
    assert all(row['recall_at_10'] is None for row in unknown)
    assert {row['evaluated_user_count'] for row in report['summary'] if row['split'] == 'dev' and row['label_source'] == 'cart'} == {9}
    assert {row['evaluated_user_count'] for row in report['summary'] if row['split'] == 'holdout' and row['label_source'] == 'cart'} == {7}
    assert all(row['mean_cpu_ms'] >= 0 for row in report['summary'])
    assert (tmp_path / 'summary.csv').exists() and (tmp_path / 'per_task.csv').exists()


def test_rejects_user_leakage_and_manifest_mismatch(tmp_path):
    tasks = build_tasks()
    bad = deepcopy(tasks)
    bad[-1]['user_id'] = bad[0]['user_id']
    with pytest.raises(ValueError, match='leak'):
        run_evaluation(tmp_path / 'bad', tasks=bad)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'artifacts': {'tasks.json': {'sha256': 'incorrect'}}}))
    with pytest.raises(ValueError, match='manifest'):
        run_evaluation(tmp_path / 'bad-manifest', tasks=tasks, manifest_path=manifest)


def test_provenance_matches_frozen_task_encoding(tmp_path):
    tasks = build_tasks()
    encoded = (json.dumps(tasks, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    digest = hashlib.sha256(encoded).hexdigest()
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'artifacts': {'tasks.json': {'sha256': digest}}}))
    report = run_evaluation(tmp_path / 'report', tasks=tasks, manifest_path=manifest)
    assert report['provenance']['tasks_sha256'] == digest
    assert report['provenance']['manifest_checked']


def test_pairwise_fits_dev_only_and_finite_reproducible_loss():
    tasks, users = build_tasks(), load_canonical_users()
    dev = [task for task in tasks if task['split'] == 'dev']
    model = PairwiseReranker(RetrievalIndex(load_canonical_items()))
    with pytest.raises(ValueError, match='holdout'):
        model.fit(tasks, users)
    report = model.fit(dev, users)
    assert math.isfinite(report['loss_after']) and report['loss_after'] <= report['loss_before']
    assert report['training_user_count'] == 9 and report['positive_count'] > 0
    assert not set(report['training_user_ids']) & {task['user_id'] for task in tasks if task['split'] == 'holdout'}
    second = PairwiseReranker(model.index)
    assert second.fit(dev, users)['weights'] == report['weights']


def test_pairwise_inference_never_reads_cart_or_ids():
    class User(dict):
        def get(self, key, default=None):
            assert key in ('preferred_categories', 'last_search_terms')
            return super().get(key, default)
    tasks, users = build_tasks(), load_canonical_users()
    model = PairwiseReranker(RetrievalIndex(load_canonical_items()))
    model.fit([task for task in tasks if task['split'] == 'dev'], users)
    sanitized = User(preferred_categories=['食品生鲜'], last_search_terms=['大米'])
    assert len(model.rank(sanitized)) == 10
    assert model.scores(sanitized) == model.scores({**sanitized, 'recent_cart_item_ids': ['i_0001'], 'user_id': 'u_9999'})


def test_learned_report_preserves_baseline_rankings_and_excludes_holdout_fit(tmp_path):
    old = run_evaluation(tmp_path / 'base')
    new = run_evaluation(tmp_path / 'learned', include_learned=True)
    assert len(new['summary']) == 24 and len(new['per_task']) == 240
    keys = lambda row: (row['task_id'], row['method'], row['label_source'])
    original = {keys(row): row['ranked_item_ids'] for row in old['per_task']}
    assert all(original[keys(row)] == row['ranked_item_ids'] for row in new['per_task'] if row['method'] in METHODS)
    assert not new['pairwise_training']['holdout_used_for_fit_or_tuning']
    assert (tmp_path / 'learned/pairwise_model.json').exists()
