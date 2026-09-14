import assert from 'node:assert/strict';
import test from 'node:test';
import { createVoiceSessionHandler } from '../lib/voice-session-handler';

const env = { OPENAI_API_KEY: 'test-provider-secret', HAYERINGUAL_VOICE_ACCESS_PASS: 'test-access-pass-not-a-provider-key-123456', HAYERINGUAL_VOICE_ENABLED: 'true', HAYERINGUAL_VOICE_EXPIRES_AT: '2026-09-18T15:00:00Z' };
const now = () => Date.parse('2026-09-15T00:00:00Z');
const input = { sdp: 'v=0\r\nprivate-offer', session: { model: 'gpt-live-1', instructions: 'private-instructions', audio: { format: { type: 'pcm' }, output: { voice: 'marin' } } } };
function request(body: unknown = input, pass = env.HAYERINGUAL_VOICE_ACCESS_PASS, ip = '192.0.2.1') {
  return new Request('https://example.test/api/fly/voice/session', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Flylingual-Voice-Pass': pass, 'X-Forwarded-For': ip }, body: JSON.stringify(body) });
}
const good = async () => Response.json({ session: { id: 'session-test', secret: 'omit' }, transport: { type: 'webrtc', sdp: 'v=0\r\nanswer', secret: 'omit' }, secret: 'omit' });
test('SDP offer and answer retain exact bytes including terminal CRLF', async () => {
  const offer = 'v=0\r\no=- 123 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n';
  const answer = 'v=0\r\no=- 456 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n';
  let calls = 0;
  const handler = createVoiceSessionHandler({ env, now, fetch: async (_, init) => {
    calls++;
    const sent = JSON.parse(String(init?.body));
    assert.deepEqual(Buffer.from(sent.transport.sdp, 'utf8'), Buffer.from(offer, 'utf8'));
    return Response.json({ session: { id: 'session-crlf' }, transport: { type: 'webrtc', sdp: answer } });
  } });
  const response = await handler(request({ ...input, sdp: offer }));
  assert.equal(response.status, 201);
  assert.equal(calls, 1);
  const received = await response.json();
  assert.deepEqual(Buffer.from(received.transport.sdp, 'utf8'), Buffer.from(answer, 'utf8'));
});
test('fixed upstream/session permissions and minimal no-store response', async () => {
  let calls = 0;
  const handler = createVoiceSessionHandler({ env, now, fetch: async (url, init) => {
    calls++; assert.equal(url, 'https://api.openai.com/v1/live/sessions');
    assert.equal(init?.redirect, 'error'); assert.equal(init?.cache, 'no-store');
    const body = JSON.parse(String(init?.body));
    assert.equal(body.session.model, 'gpt-live-1');
    assert.deepEqual(body.session.audio, { output: { voice: 'marin' } });
    assert.deepEqual(body.session.delegation, { type: 'client' });
    assert.deepEqual(body.session.client.data_channel, { allowed_client_events: ['session.instructions.append', 'session.thinking.append', 'session.commentary.append', 'session.close'], allowed_server_events: 'all' });
    return good();
  } });
  const response = await handler(request());
  assert.equal(response.status, 201); assert.equal(calls, 1);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await response.json(), { session: { id: 'session-test' }, transport: { type: 'webrtc', sdp: 'v=0\r\nanswer' } });
});
test('disabled, expired, missing or key-equal access configuration fails closed', async () => {
  for (const override of [{ HAYERINGUAL_VOICE_ENABLED: 'false' }, { HAYERINGUAL_VOICE_EXPIRES_AT: '2020-01-01T00:00:00Z' }, { HAYERINGUAL_VOICE_EXPIRES_AT: '' }, { OPENAI_API_KEY: '' }, { HAYERINGUAL_VOICE_ACCESS_PASS: '' }, { OPENAI_API_KEY: env.HAYERINGUAL_VOICE_ACCESS_PASS }]) {
    const handler = createVoiceSessionHandler({ env: { ...env, ...override }, now, fetch: async () => { assert.fail('must not contact upstream'); } });
    assert.equal((await handler(request())).status, 503);
  }
});
test('access authentication rejects missing and incorrect pass', async () => {
  const handler = createVoiceSessionHandler({ env, now, fetch: async () => { assert.fail('must not contact upstream'); } });
  for (const pass of ['', 'incorrect']) assert.equal((await handler(request(input, pass))).status, 401);
});
test('rejects model, tools, instructions length, voice and delegation overrides', async () => {
  for (const patch of [{ model: 'other' }, { tools: [] }, { instructions: 'a'.repeat(16001) }, { audio: { output: { voice: 'other' } } }, { delegation: { type: 'responses' } }, { client: { data_channel: { allowed_client_events: 'all' } } }]) {
    const handler = createVoiceSessionHandler({ env, now, fetch: async () => { assert.fail('must not contact upstream'); } });
    assert.equal((await handler(request({ ...input, session: { ...input.session, ...patch } }))).status, 400);
  }
});
test('body stream has 64KiB limit without content-length', async () => {
  const handler = createVoiceSessionHandler({ env, now, fetch: good });
  assert.equal((await handler(request({ ...input, sdp: 'x'.repeat(65537) }))).status, 413);
});
test('timeout aborts upstream without retry or secret diagnostics', async () => {
  let calls = 0; let signal: AbortSignal | null | undefined;
  const handler = createVoiceSessionHandler({ env, now, timeoutMs: 5, fetch: async (_, init) => { calls++; signal = init?.signal; return new Promise<Response>(() => {}); } });
  const response = await handler(request());
  assert.equal(response.status, 504); assert.equal(calls, 1); assert.equal(signal?.aborted, true);
  assert.deepEqual(await response.json(), { error: 'VoiceUnavailable' });
});
test('invalid/error upstream never exposes upstream or request secrets', async () => {
  for (const upstream of [async () => { throw new Error(JSON.stringify({ env, input })); }, async () => Response.json({ env, input }, { status: 401 }), async () => Response.json({ session: { id: 'x' }, transport: { type: 'other', sdp: 'x' } })]) {
    const handler = createVoiceSessionHandler({ env, now, fetch: upstream });
    const response = await handler(request());
    assert.equal(response.status, 502); assert.equal(await response.text(), '{"error":"VoiceUnavailable"}');
  }
});
test('auxiliary limits per IP/global and expire after a minute', async () => {
  let time = now();
  const handler = createVoiceSessionHandler({ env, now: () => time, fetch: good });
  for (let i = 0; i < 3; i++) assert.equal((await handler(request())).status, 201);
  assert.equal((await handler(request())).status, 429);
  for (let i = 0; i < 27; i++) assert.equal((await handler(request(input, env.HAYERINGUAL_VOICE_ACCESS_PASS, `192.0.2.${i + 2}`))).status, 201);
  assert.equal((await handler(request(input, env.HAYERINGUAL_VOICE_ACCESS_PASS, '192.0.2.100'))).status, 429);
  time += 60001; assert.equal((await handler(request())).status, 201);
});
