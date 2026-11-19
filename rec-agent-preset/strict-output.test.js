import assert from 'node:assert/strict';
import { test } from 'node:test';
import RecAgentStrictOutput, { parseStrictJson, validateRecommendation, strictOutputStream } from './strict-output.js';

function payload(reason = '原生木浆抽纸，清洁随手抽') {
  return {
    user_id: 'u_0199',
    user_profile: { city: '广州', city_tier: '一线', climate_zone: '华南', age: 38, gender: '女', life_stage: '学龄家长', active_hours: '09:00-23:00', price_sensitivity: 'low', preferred_categories: ['家居日用'], tags: ['家庭采购'] },
    recommendations: [{ item_id: 'i_0006', title: '简序 原生木浆抽纸 3层100抽×24包', exposure_reason: reason, generated_reason: reason, evidence_fields: ['items.material', 'items.functions'], context_summary: '偏好家居日用' }],
    agent_version: 'rec-agent-v2',
  };
}
async function* stream(text, extras = []) {
  yield { type: 'block-start', index: 0, blockType: 'text' };
  yield { type: 'text-delta', index: 0, text };
  yield { type: 'block-end', index: 0, block: { type: 'text', text } };
  yield* extras;
  yield { type: 'usage', usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 } };
  yield { type: 'finish', reason: { kind: 'stop' }, replayState: { adapter: 'test', blocks: ['text'] } };
}
async function drain(source) { const chunks = []; for await (const chunk of source) chunks.push(chunk); return chunks; }
function text(chunks) { return chunks.filter(chunk => chunk.type === 'text-delta').map(chunk => chunk.text).join(''); }

test('strict JSON rejects prose, fences, trailing values, NaN, duplicate/escaped keys and overflow', () => {
  for (const value of ['说明\n{}', '```json\n{}\n```', '{} {}', '{a:true}', '{"x":NaN}', '{"a":1,"a":2}', '{"a":1,"\\u0061":2}', '[{"x":1,"x":2}]', '{"x":1e400}']) {
    assert.throws(() => parseStrictJson(value), undefined, value);
  }
  assert.deepEqual(parseStrictJson('{"text":"{a:1}","nested":[{},null,true,2]}'), { text: '{a:1}', nested: [{}, null, true, 2] });
});

test('20 code point boundary includes punctuation and emoji', () => {
  assert.doesNotThrow(() => validateRecommendation(payload('好'.repeat(19) + '✨')));
  assert.throws(() => validateRecommendation(payload('好'.repeat(20) + '✨')), /20 Unicode/);
  assert.throws(() => validateRecommendation(payload('清洁\n随手抽')), /one trimmed line/);
});

test('quantities and parameters are rejected but natural numeral phrases remain valid', () => {
  for (const reason of ['24包轻松囤', '三层抽纸', '三十四厘米炒锅', '两公斤大米', '一百抽纸', '百粒维生素', '６８键键盘', 'PBT键帽', '二十四包装', '十倍清洁力', '二十个装', '一米长度', '三千瓦电器', '九十度高温', '一双鞋', '四十英尺线', '兩包抽纸', '雙層抽纸', '單層抽纸', '单层抽纸', '十几包抽纸', '十幾包抽纸', '多件装抽纸']) {
    assert.throws(() => validateRecommendation(payload(reason)), /parameter/, reason);
  }
  for (const reason of ['正红一抹，哑光显色', '不粘少油烟，三餐有滋味', '原生木浆抽纸，清洁随手抽']) assert.doesNotThrow(() => validateRecommendation(payload(reason)));
});

test('schema rejects missing, extra, wrong-type, alias and evidence errors', () => {
  const edits = [
    x => { delete x.user_profile; },
    x => { x.decision = 'expose'; },
    x => { x.recommendations[0].generated_reason = '不同'; },
    x => { x.recommendations[0].evidence_fields = ['users.tags', 'users.city']; },
    x => { x.recommendations[0].evidence_fields = ['items.material', 'history.ctr']; },
    x => { x.user_profile.age = '38'; },
    x => { x.recommendations.push({ ...x.recommendations[0] }); },
  ];
  for (const edit of edits) { const value = payload(); edit(value); assert.throws(() => validateRecommendation(value)); }
  assert.throws(() => validateRecommendation({ user_id: 'u_9999', recommendations: [], agent_version: 'rec-agent-v2' }), /context_summary/);
  assert.doesNotThrow(() => validateRecommendation({ user_id: 'u_9999', recommendations: [], context_summary: '用户不存在', agent_version: 'rec-agent-v2' }));
});

test('tool step drops prose while preserving exact tool calls and usage', async () => {
  const call = { type: 'tool-call', id: 'call1', name: 'get_item', arguments: '{"item_id":"i_0006"}' };
  const chunks = await drain(strictOutputStream(stream('我先查询商品', [
    { type: 'block-start', index: 2, blockType: 'tool-call' },
    { type: 'block-end', index: 2, block: call },
  ])));
  assert.equal(text(chunks), '');
  assert.deepEqual(chunks.find(chunk => chunk.type === 'block-end').block, call);
  assert.equal(chunks.at(-1).replayState, undefined);
  assert.equal(chunks.find(chunk => chunk.type === 'usage').usage.totalTokens, 15);
});

test('successful final becomes one indented strict JSON block', async () => {
  const value = payload();
  const chunks = await drain(strictOutputStream(stream(JSON.stringify(value))));
  const output = text(chunks);
  assert.equal(output, JSON.stringify(value, null, 2).replace(/\n/g, '  \n'));
  assert.deepEqual(parseStrictJson(output), value);
  assert.equal(chunks.filter(chunk => chunk.type === 'block-end' && chunk.block.type === 'text').length, 1);
});

test('invalid output is hidden, repaired and total usage includes repair', async () => {
  let attempts = 0;
  const chunks = await drain(strictOutputStream(stream('```json\n{}\n```'), {
    repair: ({ error, attempt }) => { attempts++; assert.equal(attempt, 1); assert.ok(error); return stream(JSON.stringify(payload())); },
  }));
  assert.equal(attempts, 1);
  assert.equal(text(chunks), JSON.stringify(payload(), null, 2).replace(/\n/g, '  \n'));
  assert.equal(chunks.find(chunk => chunk.type === 'usage').usage.totalTokens, 30);
});

test('repair is bounded and publishes no invalid final text', async () => {
  let count = 0;
  const seen = [];
  await assert.rejects(async () => {
    for await (const chunk of strictOutputStream(stream('{}'), { repair: () => { count++; return stream('{}'); } })) seen.push(chunk);
  }, /after 2 repairs/);
  assert.equal(count, 2);
  assert.equal(text(seen), '');
});

test('truncated, aborted, failed or cancelled output never publishes a prefix', async () => {
  for (const kind of ['max-tokens', 'error', 'aborted']) {
    const seen = [];
    async function* incomplete() { yield { type: 'text-delta', index: 0, text: '{"bad":' }; yield { type: 'finish', reason: { kind, failure: { code: kind, message: kind } } }; }
    try { for await (const chunk of strictOutputStream(incomplete())) seen.push(chunk); } catch (error) { assert.match(error.message, /incomplete/); }
    assert.equal(text(seen), '');
  }
  const controller = new AbortController(); controller.abort();
  await assert.rejects(drain(strictOutputStream(stream('{}'), { signal: controller.signal })), /abort/i);
});

test('plugin scopes to owning session and repairs with the same provider/model', async () => {
  const handlers = new Map(); let repairRequest;
  const ctx = { on: (name, fn) => handlers.set(name, fn), logger: { info() {} }, llm: { stream: request => {
    repairRequest = request;
    return handlers.get('llm/stream')(request, () => stream(JSON.stringify(payload())));
  } } };
  new RecAgentStrictOutput(ctx);
  await handlers.get('agent/pre-step')({ agent: { id: 'owned' } }, async () => ({}));
  const options = Object.freeze({ sessionId: 'owned', provider: 'deepseek123', model: 'deepseek-v4.1-flash-1017', reasoningEffort: 'max', messages: Object.freeze([]) });
  const chunks = await drain(handlers.get('llm/stream')(options, () => stream('{}')));
  assert.equal(parseStrictJson(text(chunks)).user_id, 'u_0199');
  assert.equal(repairRequest.provider, options.provider);
  assert.equal(repairRequest.model, options.model);
  assert.equal(repairRequest.tools, undefined);
  assert.equal(options.messages.length, 0);
  const other = handlers.get('llm/stream')({ ...options, sessionId: 'other' }, () => stream('other response'));
  assert.equal(text(await drain(other)), 'other response');
});
