/* GitHub Pages replay adapter. No credentials or model calls are used here. */
(function (scope) {
  'use strict';

  const FINISHED = new Set(['completed', 'completed_with_errors', 'error']);
  const VERSION = 'rec-agent-pages-history-v1';
  const clone = value => JSON.parse(JSON.stringify(value));

  function createStaticApi(options = {}) {
    const baseURL = options.baseURL || scope.document.baseURI;
    const assetURL = name => new URL(name, baseURL).href;
    const fetchImpl = options.fetchImpl || scope.fetch.bind(scope);
    let storage = options.storage;
    if (!storage) {
      try { storage = scope.localStorage; } catch (_) { /* Optional browser history. */ }
    }
    storage ||= {getItem: () => null, setItem() {}};
    const clock = options.now || Date.now;
    const schedule = options.schedule || scope.setTimeout.bind(scope);
    const randomID = options.randomID || (() => scope.crypto.randomUUID().replace(/-/g, ''));
    const storageKey = `${VERSION}:${new URL('.', baseURL).href}`;
    const runs = new Map();
    let ready;
    let fixtures;
    let index;

    function publicRun(run) {
      const output = clone(run);
      output.duration_seconds = Math.max(0, Math.round(((run._finished ?? clock()) - run._started) / 10) / 100);
      delete output._started;
      delete output._finished;
      return output;
    }

    function persist() {
      try {
        storage.setItem(storageKey, JSON.stringify({version: VERSION, runs: [...runs.values()].slice(-50)}));
      } catch (_) {
        // Browsing and export remain usable when browser storage is unavailable.
      }
    }

    function event(run, stage, message, progress) {
      run.stage = stage;
      run.progress = progress;
      run.events.push({stage, message, at: new Date(clock()).toISOString(), elapsed_seconds: Math.max(0, (clock() - run._started) / 1000)});
      persist();
    }

    function restore() {
      try {
        const saved = JSON.parse(storage.getItem(storageKey) || 'null');
        if (!saved || saved.version !== VERSION || !Array.isArray(saved.runs)) return;
        for (const run of saved.runs.slice(-50)) {
          if (!run || !/^[a-f0-9]{32}$/.test(run.id) || run.mode !== 'sample' || run.source !== 'saved_real_evaluation'
              || !Number.isFinite(run._started) || !Array.isArray(run.events) || !Array.isArray(run.recommendations)) continue;
          if (!FINISHED.has(run.status)) {
            run.status = 'error';
            run.stage = 'error';
            run.error = '页面已刷新，本次回放中断，请重新开始。';
            run.finished_at = new Date(clock()).toISOString();
            run._finished = clock();
            run.events.push({stage: 'error', message: '页面刷新，回放已中断', at: run.finished_at, elapsed_seconds: Math.max(0, (clock() - run._started) / 1000)});
          }
          runs.set(run.id, run);
        }
        persist();
      } catch (_) {
        // Invalid local history does not prevent a fresh replay.
      }
    }

    async function load() {
      if (!ready) ready = Promise.all([
        fetchImpl(assetURL('data/sample-runs.json')),
        fetchImpl(assetURL('data/user-index.json')),
      ]).then(async responses => {
        if (responses.some(r => !r.ok)) throw new Error('公开演示数据暂时无法加载，请刷新页面重试。');
        [fixtures, index] = await Promise.all(responses.map(r => r.json()));
        if (!Array.isArray(fixtures.samples) || !Array.isArray(index.user_ids)) throw new Error('公开演示数据格式不正确。');
        restore();
      }).catch(error => { ready = null; throw error; });
      return ready;
    }

    function summary(run) {
      const audits = run.recommendations.map(c => c.jev_audit).filter(Boolean);
      return {
        total: run.recommendations.length,
        expose: audits.filter(a => a.decision === 'expose').length,
        rewrite: audits.filter(a => a.decision === 'rewrite').length,
        errors: run.recommendations.filter(c => c.audit_status === 'error').length,
        average_score: audits.length ? Math.round(audits.reduce((sum, a) => sum + a.attractiveness_score, 0) / audits.length * 100) / 100 : null,
      };
    }

    function finish(run, message) {
      run.status = 'completed';
      run.finished_at = new Date(clock()).toISOString();
      run._finished = clock();
      run.summary = summary(run);
      event(run, 'complete', message, 100);
    }

    function create(payload) {
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)
          || Object.keys(payload).some(k => !['user_id', 'mode'].includes(k))) throw new Error('请求仅接受用户 ID 和运行模式。');
      if (!/^u_[0-9]{4}$/.test(payload.user_id || '')) throw new Error('请输入 u_0001 格式的用户 ID。');
      if ((payload.mode || 'sample') !== 'sample') throw new Error('GitHub Pages 提供真实历史结果演示；实时生成请使用本地工作台。');
      const sample = fixtures.samples.find(s => s.user_id === payload.user_id);
      if (index.user_ids.includes(payload.user_id) && !sample) throw new Error('该用户暂无公开实测记录，请选择 u_0001、u_0199 或 u_0007；其他用户可在本地实时生成。');
      if ([...runs.values()].filter(r => !FINISHED.has(r.status)).length >= 6) throw new Error('回放队列已满，请等待当前回放结束。');
      if (runs.size >= 50) {
        const oldest = [...runs.values()].find(r => FINISHED.has(r.status));
        if (oldest) runs.delete(oldest.id);
      }
      const started = clock();
      const run = {
        id: randomID(), user_id: payload.user_id, mode: 'sample', status: 'queued', stage: 'context', progress: 0,
        source: 'saved_real_evaluation', hosting: 'github-pages', history_source: 'browser_local',
        created_at: new Date(started).toISOString(), finished_at: null, _started: started,
        profile: null, history: null, recommendations: [], summary: null, events: [], error: null,
        recommendation_model: 'deepseek-v4.1-flash-1017', jev_model: 'jev-1.14.0',
        scenario_date: index.scenario_date || '2026-06-15',
        question_schema_version: 'jev-questions-v4-two', policy_version: 'jev-two-policy-v1',
        network_calls: {recommendation: 0, jev: 0}, recorded_at: sample?.recorded_at || null,
      };
      runs.set(run.id, run);
      event(run, 'context', '载入公开实测数据中的用户画像与反馈摘要', 10);
      schedule(() => {
        run.status = 'running';
        if (!sample) {
          run.empty_reason = '规范用户数据中未找到该用户，未生成推荐或调用模型。';
          finish(run, '未找到该用户，回放结束，模型调用为 0');
          return;
        }
        run.profile = clone(sample.profile);
        run.history = clone(sample.history);
        event(run, 'generating', '载入已保存的桌面 Harness 推荐与曝光理由', 32);
      }, 180);
      if (sample) {
        schedule(() => {
          run.recommendations = clone(sample.recommendations).map(card => ({...card, audit_status: 'pending', jev_audit: null}));
          event(run, 'auditing', '载入同一轮真实 Jev 风险选择与吸引力记录', 60);
        }, 450);
        sample.recommendations.forEach((card, i) => schedule(() => {
          run.recommendations[i] = {...clone(card), audit_status: 'completed'};
          event(run, 'auditing', `已载入 ${i + 1}/${sample.recommendations.length} 条真实审核记录`, 60 + Math.round(35 * (i + 1) / sample.recommendations.length));
        }, 700 + i * 200));
        schedule(() => finish(run, '历史实测结果已载入，本次未调用推荐模型或 Jev'), 950 + sample.recommendations.length * 200);
      }
      persist();
      return publicRun(run);
    }

    async function request(path, options = {}) {
      const method = (options.method || 'GET').toUpperCase();
      if (method === 'POST' && path === '/api/runs') {
        let payload;
        try { payload = JSON.parse(options.body); } catch (_) { throw new Error('输入必须是完整 JSON。'); }
        // Reject live mode before even reading static fixtures.
        if (payload?.mode && payload.mode !== 'sample') throw new Error('GitHub Pages 提供真实历史结果演示；实时生成请使用本地工作台。');
        await load();
        return create(payload);
      }
      await load();
      if (method === 'GET' && path === '/api/config') return {
        hosting: 'github-pages', history_source: 'browser_local', live_available: false,
        recommendation_model: 'deepseek-v4.1-flash-1017', recommendation_provider: '已录制桌面 Harness', jev_model: 'jev-1.14.0',
        user_count: index.user_count ?? index.user_ids.length, item_count: index.item_count ?? 200,
        scenario_date: index.scenario_date || '2026-06-15',
        question_schema_version: 'jev-questions-v4-two', policy_version: 'jev-two-policy-v1',
        credentials: {recommendation_configured: false, jev_configured: false},
        sample_users: fixtures.samples.map(s => ({user_id: s.user_id, city: s.profile.city, life_stage: s.profile.life_stage, history_status: s.history.history_status})),
      };
      if (method === 'GET' && path === '/api/runs') return {runs: [...runs.values()].slice(-20).reverse().map(publicRun)};
      const match = /^\/api\/runs\/([a-f0-9]{32})(\/export)?$/.exec(path);
      if (method === 'GET' && match) {
        const run = runs.get(match[1]);
        if (!run) throw new Error('未找到本浏览器中的回放记录。');
        return publicRun(run);
      }
      throw new Error('公开演示不支持此操作。');
    }

    async function exportRun(id) {
      const run = await request(`/api/runs/${id}/export`);
      const blob = new scope.Blob([JSON.stringify(run, null, 2) + '\n'], {type: 'application/json;charset=utf-8'});
      const url = scope.URL.createObjectURL(blob);
      const link = scope.document.createElement('a');
      link.href = url;
      link.download = `rec-agent-${id}.json`;
      scope.document.body.append(link);
      link.click();
      link.remove();
      schedule(() => scope.URL.revokeObjectURL(url), 1000);
    }

    return {request, exportRun};
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = {createStaticApi};
  if (scope.document?.querySelector('meta[name="rec-agent-hosting"][content="github-pages"]')) {
    scope.recStaticApi = createStaticApi();
  }
})(globalThis);
