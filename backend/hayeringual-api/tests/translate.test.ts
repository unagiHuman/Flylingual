import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createTranslateHandler } from '../lib/translate-handler';
import { runtimeConfig } from '../lib/ai-client';
import { CODES, flyRequestSchema } from '../lib/fly-schema';
import { GET } from '../app/api/health/route';
import { APICallError } from 'ai';
import { GatewayAuthenticationError, GatewayModelNotFoundError, GatewayInternalServerError } from '@ai-sdk/gateway';
import { safeErrorDiagnostic } from '../lib/errors';

const input = { schemaVersion: 1, playerInput: '右に進んで', language: 'ja',
  flyState: { active: false, candidate: false, activeForward: false,
    activeNudge: false, defaultMs: 1000, maxMs: 120000 } };
const request = (data: unknown = input) => new Request('http://localhost/api/fly/translate', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
const silent = () => {};

test('valid existing intent round trips; health contains no configuration', async () => {
  const handler = createTranslateHandler(async value => {
    assert.deepEqual(value, input); return { c: 'right_then_forward', speech: '右だね。' };
  }, silent);
  const response = await handler(request());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { schemaVersion: 1, c: 'right_then_forward', speech: '右だね。' });
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await GET().json(), { ok: true, service: 'hayeringual-api', version: '1' });
});

test('invalid/version/unknown/oversized semantic fields rejected before inference', async () => {
  let calls = 0;
  const handler = createTranslateHandler(async () => { calls++; return {}; }, silent);
  for (const data of [{ ...input, schemaVersion: 2 }, { ...input, neuron: 100 },
    { ...input, playerInput: 'x'.repeat(1001) }, { ...input, playerInput: ' ' },
    { ...input, language: 'fr' }, { ...input, flyState: { ...input.flyState, reward: 1 } },
    { ...input, flyState: { ...input.flyState, active: 'false' } },
    { ...input, flyState: { ...input.flyState, maxMs: 10 } }])
    assert.equal((await handler(request(data))).status, 400);
  assert.equal(calls, 0);
});

test('streaming body bound works without trusted Content-Length', async () => {
  const handler = createTranslateHandler(async () => { assert.fail('must not infer'); }, silent);
  const stream = new ReadableStream({ start(c) {
    c.enqueue(new Uint8Array(9000)); c.enqueue(new Uint8Array(9000)); c.close();
  } });
  const req = new Request('http://localhost', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: stream, duplex: 'half' } as RequestInit);
  assert.equal((await handler(req)).status, 413);
  const bad = new Request('http://localhost', { method: 'POST', body: '{bad',
    headers: { 'Content-Type': 'application/json' } });
  assert.equal((await handler(bad)).status, 400);
  assert.equal((await handler(new Request('http://localhost', { method: 'POST', body: '{}' }))).status, 415);
});

test('provider 402 and malformed model output become CloudUnavailable without leaks', async () => {
  for (const infer of [async () => { throw { statusCode: 402, message: 'SECRET response body' }; },
    async () => ({ c: 'invented', speech: 'foo' }),
    async () => ({ c: 'FORWARD', speech: 'x'.repeat(161) }),
    async () => ({ c: 'FORWARD', speech: 'yes', motor: 1 })]) {
    const events: unknown[] = [];
    const result = await createTranslateHandler(infer, e => events.push(e))(request());
    assert.equal(result.status, 503);
    assert.deepEqual(await result.json(), { schemaVersion: 1, error: 'CloudUnavailable' });
    assert.doesNotMatch(JSON.stringify(events), /SECRET|右に|playerInput|flyState/);
  }
});

test('hard deadline stops waiting even when inference ignores abort', async () => {
  const prior = process.env.HAYERINGUAL_TIMEOUT_MS;
  process.env.HAYERINGUAL_TIMEOUT_MS = '100';
  try {
    let seenSignal: AbortSignal | undefined;
    const handler = createTranslateHandler(async (_, signal) => {
      seenSignal = signal; return await new Promise(() => {});
    }, silent);
    const start = performance.now();
    assert.equal((await handler(request())).status, 503);
    assert.equal(seenSignal?.aborted, true);
    assert.ok(performance.now() - start < 1000);
  } finally {
    if (prior === undefined) delete process.env.HAYERINGUAL_TIMEOUT_MS;
    else process.env.HAYERINGUAL_TIMEOUT_MS = prior;
  }
});

test('client abort cancels inference', async () => {
  const abort = new AbortController();
  const req = new Request(request(), { signal: abort.signal });
  const handler = createTranslateHandler(async (_, signal) => {
    abort.abort(); assert.equal(signal.aborted, true); return await new Promise(() => {});
  }, silent);
  assert.equal((await handler(req)).status, 503);
});

test('runtime limits cannot disable the budget/deadline settings', () => {
  assert.deepEqual(runtimeConfig({}), { model: 'google/gemini-3.5-flash-lite', reasoning: 'minimal',
    maxOutputTokens: 96, timeoutMs: 4000 });
  for (const env of [{ HAYERINGUAL_TIMEOUT_MS: 'NaN' }, { HAYERINGUAL_TIMEOUT_MS: '5000' },
    { HAYERINGUAL_MAX_OUTPUT_TOKENS: '10000' }, { HAYERINGUAL_REASONING: 'high' },
    { HAYERINGUAL_LLM_MODEL: 'https://example.com' }]) assert.throws(() => runtimeConfig(env));
});

test('classification enum stays aligned with existing Bridge codes', () => {
  const bridge = new URL('../../../Runtime/Bridge/', import.meta.url);
  const control = readFileSync(new URL('control.py', bridge), 'utf8');
  const plans = readFileSync(new URL('action_plans.py', bridge), 'utf8');
  const actions = [...control.match(/ACTIONS = \(([^\n]+)\)/)![1].matchAll(/'([^']+)'/g)].map(m => m[1]);
  const planKeys = [...plans.split('PLAN_STEPS = {')[1].split('}')[0].matchAll(/'([^']+)':/g)].map(m => m[1]);
  assert.deepEqual([...CODES], [...actions, ...planKeys, 'continue', 'conditions', 'question', 'clarify']);
});

test('optional neural observations preserve freshness without claiming body movement', () => {
  for (const observation of [
    { fresh: true, forward: 0.61, turn: -0.12, bodyMovementVerified: false },
    { fresh: false, forward: null, turn: null, bodyMovementVerified: false },
    { fresh: false, forward: 0.61, turn: -0.12, bodyMovementVerified: false },
  ]) assert.deepEqual(flyRequestSchema.parse({ ...input,
    flyState: { ...input.flyState, observation } }).flyState.observation, observation);
  for (const change of [{ bodyMovementVerified: true }, { forward: Infinity },
    { forward: 1001 }, { turn: -1001 }, { reward: 1 }, { fresh: 'yes' }]) {
    const observation = { fresh: true, forward: 0, turn: null, bodyMovementVerified: false, ...change };
    assert.equal(flyRequestSchema.safeParse({ ...input,
      flyState: { ...input.flyState, observation } }).success, false);
  }
});

test('safe diagnostics identify SDK status without provider messages or arbitrary names', async () => {
  assert.deepEqual(safeErrorDiagnostic(new GatewayAuthenticationError({ message: 'SECRET' })),
    { errorKind: 'GatewayAuthenticationError', upstreamStatus: 401, reasonCode: 'Unclassified' });
  assert.deepEqual(safeErrorDiagnostic(new GatewayModelNotFoundError({ message: 'SECRET', modelId: 'SECRET' })),
    { errorKind: 'GatewayModelNotFoundError', upstreamStatus: 404, reasonCode: 'Unclassified' });
  const error = new APICallError({ message: 'SECRET provider message', url: 'https://secret.example',
    requestBodyValues: { secret: 'SECRET' }, statusCode: 402, responseBody: 'SECRET body' });
  assert.deepEqual(safeErrorDiagnostic(error), { errorKind: 'APICallError', upstreamStatus: 402 });
  assert.deepEqual(safeErrorDiagnostic({ name: 'SECRET', statusCode: 402 }), { errorKind: 'UnknownError' });
  const events: unknown[] = [];
  const result = await createTranslateHandler(async () => { throw error; }, e => events.push(e))(request());
  assert.equal(result.status, 503);
  assert.doesNotMatch(JSON.stringify(events), /SECRET|secret.example|responseBody/);
  assert.match(JSON.stringify(events), /APICallError/);
});

test('Gateway reason diagnostics only emit fixed categories', () => {
  for (const [message, reasonCode] of [
    ['SECRET insufficient credits', 'BillingOrCredits'],
    ['SECRET invalid API key', 'AuthenticationOrPermission'],
    ['SECRET model not available', 'ModelUnavailable'],
    ['SECRET unsupported region', 'RegionRestriction'],
    ['SECRET deployment protection', 'DeploymentProtection'],
    ['SECRET mysterious failure', 'Unclassified'],
  ]) {
    const result = safeErrorDiagnostic(new GatewayInternalServerError({ message: 'Gateway failed',
      statusCode: 403, cause: new Error(message) }));
    assert.equal(result.reasonCode, reasonCode);
    assert.doesNotMatch(JSON.stringify(result), /SECRET|Gateway failed/);
  }
});
