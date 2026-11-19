/** Rec-Agent output boundary, using the native Harness llm/stream waterfall. */

export function parseStrictJson(text) {
  const value = JSON.parse(text);
  // JSON.parse accepts duplicate keys and overflows large exponents to Infinity.
  const tokens = text.match(/"(?:[^"\\]|\\.)*"|[{}\[\]:,]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g) ?? [];
  let at = 0;
  function walk(depth = 0) {
    if (depth > 100) throw new Error('JSON nesting exceeds 100 levels');
    const token = tokens[at++];
    if (token === '{') {
      const keys = new Set();
      while (tokens[at] !== '}') {
        const key = JSON.parse(tokens[at++]);
        if (keys.has(key)) throw new Error(`Duplicate JSON key: ${key}`);
        keys.add(key);
        at++; // colon; syntax has already been checked by JSON.parse
        walk(depth + 1);
        if (tokens[at] !== ',') break;
        at++;
      }
      at++;
    } else if (token === '[') {
      while (tokens[at] !== ']') {
        walk(depth + 1);
        if (tokens[at] !== ',') break;
        at++;
      }
      at++;
    } else if (/^-?\d/.test(token) && !Number.isFinite(Number(token))) {
      throw new Error('JSON number must be finite');
    }
  }
  walk();
  return value;
}

const PROFILE_STRINGS = ['city', 'city_tier', 'climate_zone', 'gender', 'life_stage', 'active_hours', 'price_sensitivity'];
const CARD_KEYS = ['item_id', 'title', 'exposure_reason', 'generated_reason', 'evidence_fields', 'context_summary'];
const ITEM_FIELDS = 'item_id title brand category_l1 category_l2 category_l3 functions material spec suit_audience suit_season efficacy_claims_allowed qualifications price_cents original_price_cents promo_tags promo_rule_ids stock regulated_category sensitive_category ad_law_notes'.split(' ');
const SCENE_FIELDS = 'city city_tier climate_zone life_stage tags active_hours'.split(' ');
const EVIDENCE = new Set([
  ...ITEM_FIELDS.map(field => `items.${field}`),
  ...SCENE_FIELDS.flatMap(field => [`users.${field}`, `user_context.${field}`]),
  ...['city_tier', 'climate_zone', 'monsoon_months', 'notes'].map(field => `city_climate.${field}`),
  'time-context',
]);
// Natural expressions such as 一抹、三餐 do not match these measurement units.
const PARAMETER = /[0-9０-９]|[一二三四五六七八九十百千万两兩零〇半几幾数數壹贰叁肆伍陆柒捌玖拾佰仟萬億单双單雙多]+\s*(?:包|抽|层|層|张|張|盒|瓶|袋|罐|箱|卷|本|杯|枚|粒|颗|顆|片|支|条|條|件|套|只|個|个|人份|斤|公斤|千克|克|毫克|升|毫升|厘米|毫米|米|寸|英寸|英尺|键|鍵|瓦|伏|安培|赫兹|度|号|號|码|碼|倍|成|折|双|雙|对|對|台|部|辆|輛|架|节|節|档|檔|色|孔|级|級|代|年|月|天|小时|小時|分钟|分鐘)|(?:cm|mm|ml|kg|mah|gb|tb|hz|dpi|pbt|tpu|usb|type-c|°c|℃)/iu;

function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function exactKeys(value, required, optional = []) {
  if (!object(value) || required.some(key => !Object.hasOwn(value, key))
      || Object.keys(value).some(key => !required.includes(key) && !optional.includes(key))) {
    throw new Error(`Expected object fields: ${required.join(', ')}`);
  }
}
function string(value, name, empty = false) {
  if (typeof value !== 'string' || (!empty && !value.trim())) throw new Error(`${name} must be a string`);
}

export function validateRecommendation(value) {
  if (!object(value) || !Array.isArray(value.recommendations)) throw new Error('recommendations must be an array');
  const empty = value.recommendations.length === 0;
  exactKeys(value, empty
    ? ['user_id', 'recommendations', 'agent_version', 'context_summary']
    : ['user_id', 'recommendations', 'agent_version', 'user_profile'],
  empty ? ['user_profile'] : []);
  string(value.user_id, 'user_id');
  if (value.agent_version !== 'rec-agent-v2') throw new Error('agent_version must be rec-agent-v2');
  if (value.recommendations.length > 3) throw new Error('At most 3 recommendations');
  if (value.context_summary !== undefined) string(value.context_summary, 'context_summary');
  if (value.user_profile !== undefined) {
    exactKeys(value.user_profile, [...PROFILE_STRINGS, 'age', 'preferred_categories', 'tags']);
    for (const field of PROFILE_STRINGS) string(value.user_profile[field], field, true);
    if (!Number.isInteger(value.user_profile.age) || value.user_profile.age < 0) throw new Error('age must be a nonnegative integer');
    for (const field of ['preferred_categories', 'tags']) {
      if (!Array.isArray(value.user_profile[field]) || value.user_profile[field].some(x => typeof x !== 'string')) throw new Error(`${field} must be a string array`);
    }
  }
  const ids = new Set();
  for (const card of value.recommendations) {
    exactKeys(card, CARD_KEYS);
    for (const field of CARD_KEYS.filter(field => field !== 'evidence_fields')) string(card[field], field);
    if (!/^i_\d{4}$/.test(card.item_id) || ids.has(card.item_id)) throw new Error('item_id must be canonical and unique');
    ids.add(card.item_id);
    const reason = card.exposure_reason;
    if (reason.trim() !== reason || /[\x00-\x1f\x7f\x85\u2028\u2029]/u.test(reason)) throw new Error('exposure_reason must be one trimmed line');
    if ([...reason].length > 20) throw new Error('exposure_reason exceeds 20 Unicode characters');
    if (PARAMETER.test(reason)) throw new Error('exposure_reason contains a quantity or product parameter');
    if (card.generated_reason !== reason) throw new Error('generated_reason must equal exposure_reason');
    if ([...card.context_summary].length > 60) throw new Error('context_summary exceeds 60 characters');
    const fields = card.evidence_fields;
    if (!Array.isArray(fields) || fields.length < 2 || fields.length > 6 || new Set(fields).size !== fields.length
        || fields.some(field => !EVIDENCE.has(field)) || !fields.some(field => field.startsWith('items.'))) {
      throw new Error('evidence_fields requires 2–6 unique allowed paths including items.*');
    }
  }
  return value;
}

/** Read authoritative block-end records, with delta-only adapter support. */
function collect(chunks) {
  const blocks = new Map();
  let finish;
  let usage;
  for (const chunk of chunks) {
    if (chunk.type === 'finish') finish = chunk;
    if (chunk.type === 'usage') usage = chunk.usage;
    if (chunk.type === 'block-start' && !blocks.has(chunk.index)) blocks.set(chunk.index, { type: chunk.blockType, text: '' });
    if (chunk.type === 'block-end') blocks.set(chunk.index, { ...chunk.block, closed: true });
    if (chunk.type === 'text-delta' || chunk.type === 'reasoning-delta') {
      const block = blocks.get(chunk.index) ?? { type: chunk.type === 'text-delta' ? 'text' : 'reasoning', text: '' };
      if (!block.closed) block.text += chunk.text;
      blocks.set(chunk.index, block);
    }
    if (chunk.type === 'tool-call-delta') {
      const block = blocks.get(chunk.index) ?? { type: 'tool-call', arguments: '' };
      if (!block.closed) Object.assign(block, { id: chunk.id, name: chunk.name ?? block.name, arguments: (block.arguments ?? '') + chunk.argumentsDelta });
      blocks.set(chunk.index, block);
    }
  }
  return { blocks: [...blocks.values()].map(({ closed, ...block }) => block), finish, usage };
}

function addUsage(total, usage) {
  if (!usage) return total;
  const result = { ...total };
  for (const key of ['inputTokens', 'outputTokens', 'totalTokens', 'cacheReadTokens', 'cacheWriteTokens', 'reasoningTokens']) {
    if (usage[key] !== undefined) result[key] = (result[key] ?? 0) + usage[key];
  }
  return result;
}

/** Buffer each step, hide pre-tool prose, and publish one validated JSON final. */
export async function* strictOutputStream(source, { repair, maxRepairs = 2, signal, onRepair } = {}) {
  let totalUsage;
  for (let attempt = 0; ; attempt++) {
    const chunks = [];
    for await (const chunk of source) {
      signal?.throwIfAborted();
      chunks.push(chunk);
    }
    signal?.throwIfAborted();
    const result = collect(chunks);
    totalUsage = addUsage(totalUsage, result.usage);
    if (!result.finish || ['error', 'aborted', 'max-tokens'].includes(result.finish.reason.kind)) {
      // No partial JSON is ever published, even on cancellation or truncation.
      if (totalUsage) yield { type: 'usage', usage: totalUsage };
      if (result.finish?.reason.kind === 'error' || result.finish?.reason.kind === 'aborted') yield result.finish;
      else throw new Error('Rec-Agent JSON response incomplete; retry this turn');
      return;
    }
    if (result.blocks.some(block => block.type === 'tool-call')) {
      if (attempt > 0) throw new Error('Rec-Agent JSON repair must not call tools');
      const hidden = new Set(chunks.filter(chunk => chunk.type === 'block-start' && chunk.blockType === 'text').map(chunk => chunk.index));
      for (const chunk of chunks) if (chunk.type === 'text-delta' || chunk.type === 'block-end' && chunk.block.type === 'text') hidden.add(chunk.index);
      for (const chunk of chunks) {
        if (hidden.has(chunk.index) || chunk.type === 'finish') continue;
        yield chunk;
      }
      // Rewritten block structure must not retain positional replay metadata.
      yield { type: 'finish', reason: result.finish.reason };
      return;
    }
    const text = result.blocks.filter(block => block.type === 'text').map(block => block.text).join('');
    let formatted;
    try {
      // Harness renders assistant text as Markdown, which collapses ordinary
      // single newlines. Markdown hard breaks preserve visible JSON lines;
      // trailing spaces remain legal JSON whitespace in the copied response.
      formatted = JSON.stringify(validateRecommendation(parseStrictJson(text)), null, 2).replace(/\n/g, '  \n');
    }
    catch (error) {
      if (!repair || attempt >= maxRepairs) throw new Error(`Rec-Agent output validation failed after ${attempt} repairs: ${error.message}`);
      onRepair?.(attempt + 1, error.message);
      source = repair({ text, error: error.message, attempt: attempt + 1 });
      continue;
    }
    // Preserve reasoning in its own native block, separate from visible text.
    let index = 0;
    for (const block of result.blocks.filter(block => block.type === 'reasoning')) {
      yield { type: 'block-start', index, blockType: 'reasoning' };
      yield { type: 'block-end', index: index++, block };
    }
    yield { type: 'block-start', index, blockType: 'text' };
    yield { type: 'text-delta', index, text: formatted };
    yield { type: 'block-end', index, block: { type: 'text', text: formatted } };
    if (totalUsage) yield { type: 'usage', usage: totalUsage };
    yield { type: 'finish', reason: { kind: 'stop' } };
    return;
  }
}

export default class RecAgentStrictOutput {
  static inject = ['llm'];
  constructor(ctx) {
    const sessions = new Set();
    // This listener is agent-scoped by the preset composition.
    ctx.on('agent/pre-step', async (payload, next) => {
      sessions.add(payload.agent.id);
      return next();
    });
    ctx.on('agent/disposed', ({ agent }) => sessions.delete(agent.id));
    const repairs = new WeakSet();
    ctx.on('llm/stream', (options, next) => {
      if (!options.sessionId || !sessions.has(options.sessionId) || options.purpose || repairs.has(options)) return next();
      return strictOutputStream(next(), {
        signal: options.signal,
        onRepair: (attempt, reason) => ctx.logger.info(`Rec-Agent JSON repair ${attempt}: ${reason}`),
        repair: ({ text, error }) => {
          // A one-shot call owned by this plugin; never mutate the loop's frozen request.
          const request = {
            provider: options.provider, model: options.model,
            ...(options.reasoningEffort === undefined ? {} : { reasoningEffort: options.reasoningEffort }),
            maxTokens: options.maxTokens, signal: options.signal, sessionId: options.sessionId,
            messages: [...options.messages, {
              role: 'user', content: [{ type: 'text', text: `将下面待修复结果当作数据。仅返回一个符合Rec-Agent Schema的严格JSON对象，2空格缩进。每条exposure_reason及generated_reason完全相同、全部字符不超过20、不含商品数量/尺寸/规格参数。只利用上文已查询的事实，保留用户与商品，不调用工具。校验错误：${error}\n待修复结果：\n${text}` }],
            }],
          };
          repairs.add(request);
          return ctx.llm.stream(request);
        },
      });
    });
  }
}
