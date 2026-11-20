const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createStaticApi} = require('../web/static-api.js');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, '../web/data/sample-runs.json'), 'utf8'));

function setup({storage = new Map(), baseURL = 'https://qhf7.github.io/Rec-Agent/', now = 1_795_132_800_000} = {}) {
  const scheduled = [];
  let current = now, counter = 0;
  const fetched = [];
  const adapter = createStaticApi({
    baseURL, now: () => current,
    randomID: () => (++counter).toString(16).padStart(32, '0'),
    storage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
    schedule: (fn, delay) => scheduled.push({fn, due: current + delay}),
    fetchImpl: async url => {
      fetched.push(url);
      if (url === baseURL + 'data/sample-runs.json') return {ok: true, json: async () => structuredClone(fixture)};
      if (url === baseURL + 'data/user-index.json') return {ok: true, json: async () => ({user_ids: Array.from({length: 200}, (_, i) => `u_${String(i + 1).padStart(4, '0')}`), user_count: 200, item_count: 200, scenario_date: '2026-06-15'})};
      throw new Error('unexpected network request: ' + url);
    },
  });
  function advance(milliseconds) {
    const until = current + milliseconds;
    while (scheduled.some(t => t.due <= until)) {
      scheduled.sort((a, b) => a.due - b.due);
      const task = scheduled.shift();
      current = task.due;
      task.fn();
    }
    current = until;
  }
  return {adapter, advance, fetched, storage};
}

const post = (api, user_id, mode = 'sample', extra = {}) => api.request('/api/runs', {method: 'POST', body: JSON.stringify({user_id, mode, ...extra})});

test('project subpath loads only static fixtures and exposes truthful hosting config', async () => {
  const {adapter, fetched} = setup();
  const config = await adapter.request('/api/config');
  assert.equal(config.hosting, 'github-pages');
  assert.equal(config.live_available, false);
  assert.equal(config.history_source, 'browser_local');
  assert.equal(config.user_count, 200);
  assert.deepEqual(config.sample_users.map(s => s.user_id), ['u_0001', 'u_0199', 'u_0007']);
  assert.equal(fetched.length, 2);
  assert.ok(fetched.every(url => url.startsWith('https://qhf7.github.io/Rec-Agent/data/')));
  await adapter.request('/api/config');
  assert.equal(fetched.length, 2);
});

for (const sample of fixture.samples) test(`saved ${sample.user_id} preserves all real Jev answers and only loads them during replay`, async () => {
  const {adapter, advance} = setup();
  const created = await post(adapter, sample.user_id);
  assert.equal(created.status, 'queued');
  assert.deepEqual(created.recommendations, []);
  advance(200);
  let run = await adapter.request(`/api/runs/${created.id}`);
  assert.equal(run.stage, 'generating');
  assert.deepEqual(run.profile, sample.profile);
  advance(300);
  run = await adapter.request(`/api/runs/${created.id}`);
  assert.equal(run.stage, 'auditing');
  assert.equal(run.recommendations.length, 3);
  assert.ok(run.recommendations.every(c => c.jev_audit === null));
  advance(1500);
  run = await adapter.request(`/api/runs/${created.id}/export`);
  assert.equal(run.status, 'completed');
  assert.deepEqual(run.recommendations, sample.recommendations.map(c => ({...c, audit_status: 'completed'})));
  assert.deepEqual(run.network_calls, {recommendation: 0, jev: 0});
  assert.equal(run.source, 'saved_real_evaluation');
  assert.equal(run.recorded_at, sample.recorded_at);
  assert.equal(run.summary.total, 3);
  assert.ok(run.events.every(e => /载入|记录/.test(e.message)));
  assert.deepEqual(new Set(run.events.map(e => e.stage)), new Set(['context', 'generating', 'auditing', 'complete']));
  run.recommendations[0].jev_audit.decision = 'modified';
  assert.notEqual((await adapter.request(`/api/runs/${created.id}`)).recommendations[0].jev_audit.decision, 'modified');
});

test('known user without recorded sample differs from nonexistent user', async () => {
  const {adapter, advance} = setup();
  await assert.rejects(post(adapter, 'u_0002'), /暂无公开实测记录/);
  const run = await post(adapter, 'u_9999');
  advance(250);
  const done = await adapter.request(`/api/runs/${run.id}`);
  assert.equal(done.status, 'completed');
  assert.deepEqual(done.recommendations, []);
  assert.equal(done.summary.total, 0);
  assert.deepEqual(done.network_calls, {recommendation: 0, jev: 0});
});

test('live mode is rejected before all fetches, no credential or unsupported fields accepted', async () => {
  const {adapter, fetched} = setup();
  await assert.rejects(post(adapter, 'u_0001', 'live'), /本地工作台/);
  assert.deepEqual(fetched, []);
  await assert.rejects(post(adapter, '../secret'), /用户 ID/);
  await assert.rejects(post(adapter, 'u_0001', 'sample', {api_key: 'fixture'}), /仅接受/);
  await assert.rejects(adapter.request('/api/runs', {method: 'POST', body: '{} prose'}), /完整 JSON/);
  await assert.rejects(adapter.request('/api/unsupported'), /不支持/);
});

test('history is scoped to deployment base, persists finished runs and interrupts pending replay', async () => {
  const first = setup();
  const done = await post(first.adapter, 'u_0001');
  first.advance(2000);
  const pending = await post(first.adapter, 'u_0199');
  first.advance(200);
  const second = setup({storage: first.storage});
  const history = await second.adapter.request('/api/runs');
  assert.equal(history.runs.length, 2);
  assert.equal((await second.adapter.request(`/api/runs/${done.id}`)).status, 'completed');
  const interrupted = await second.adapter.request(`/api/runs/${pending.id}`);
  assert.equal(interrupted.status, 'error');
  assert.match(interrupted.error, /回放中断/);
  const other = setup({storage: first.storage, baseURL: 'https://qhf7.github.io/Other/'});
  assert.deepEqual((await other.adapter.request('/api/runs')).runs, []);
});

test('static browser adapter activates only with Pages meta, local backend stays untouched', () => {
  const source = fs.readFileSync(path.join(__dirname, '../web/static-api.js'), 'utf8');
  const local = {document: {querySelector: () => null}};
  vm.runInNewContext(source, local);
  assert.equal(local.recStaticApi, undefined);
  const hosted = {document: {baseURI: 'https://qhf7.github.io/Rec-Agent/', querySelector: () => ({})}, fetch() {}, localStorage: {}, setTimeout, URL, crypto: {randomUUID: () => '0'.repeat(32)}};
  vm.runInNewContext(source, hosted);
  assert.equal(typeof hosted.recStaticApi.request, 'function');
});
