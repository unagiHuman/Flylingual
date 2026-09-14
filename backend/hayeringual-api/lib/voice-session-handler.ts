import { createHash, timingSafeEqual } from 'node:crypto';
import { z } from 'zod';

const voices = ['marin', 'quartz', 'ripple', 'vesper', 'willow', 'stone', 'gleam', 'meridian', 'bossa', 'tempo', 'beacon', 'delta', 'cinder'] as const;
const bodySchema = z.object({
  sdp: z.string().min(1).refine(value => value.trim().length > 0),
  session: z.object({
    model: z.literal('gpt-live-1'), instructions: z.string().max(16000),
    delegation: z.object({ type: z.literal('client') }).strict().optional(),
    audio: z.object({
      format: z.unknown().optional(),
      output: z.object({ voice: z.enum(voices) }).strict().optional(),
    }).strict().optional(),
  }).strict(),
}).strict();
const answerSchema = z.object({
  session: z.object({ id: z.string().min(1).max(256) }),
  transport: z.object({ type: z.literal('webrtc'), sdp: z.string().min(1).max(65536) }),
});
class Failure extends Error { constructor(readonly status: number) { super('VoiceUnavailable'); } }
const reply = (status: number, body: unknown) => Response.json(body, { status, headers: { 'Cache-Control': 'no-store' } });

async function readBody(req: Request, signal: AbortSignal): Promise<unknown> {
  if (req.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') throw new Failure(415);
  const length = req.headers.get('content-length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > 65536)) throw new Failure(413);
  if (!req.body) throw new Failure(400);
  const reader = req.body.getReader(), chunks: Uint8Array[] = [];
  let total = 0;
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', cancel, { once: true });
  try {
    while (true) {
      signal.throwIfAborted();
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      total += value.byteLength;
      if (total > 65536) { cancel(); throw new Failure(413); }
      chunks.push(value);
    }
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); }
    catch { throw new Failure(400); }
  } finally { signal.removeEventListener('abort', cancel); reader.releaseLock(); }
}

type Options = { fetch?: typeof fetch; env?: Record<string, string | undefined>; now?: () => number; timeoutMs?: number };
export function createVoiceSessionHandler(options: Options = {}) {
  const upstream = options.fetch ?? fetch, now = options.now ?? Date.now;
  // Instance-local auxiliary limit, NOT a distributed quota or session-duration limit.
  // Deploy behind a trusted proxy/WAF: forwarded IP headers are not authentication.
  const ips = new Map<string, number[]>();
  let global: number[] = [];
  return async (req: Request): Promise<Response> => {
    const env = options.env ?? process.env, time = now();
    const pass = env.HAYERINGUAL_VOICE_ACCESS_PASS ?? '', key = env.OPENAI_API_KEY ?? '';
    const expiry = env.HAYERINGUAL_VOICE_EXPIRES_AT ?? '';
    if (env.HAYERINGUAL_VOICE_ENABLED !== 'true' || !key.trim() || pass.length < 32 || pass.length > 512 || pass === key ||
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(expiry) || !(Date.parse(expiry) > time))
      return reply(503, { error: 'VoiceUnavailable' });
    const offered = req.headers.get('X-Flylingual-Voice-Pass') ?? '';
    const digest = (value: string) => createHash('sha256').update(value).digest();
    if (offered.length > 512 || !timingSafeEqual(digest(offered), digest(pass))) return reply(401, { error: 'Unauthorized' });
    global = global.filter(t => t > time - 60000);
    for (const [ip, times] of ips) {
      const fresh = times.filter(t => t > time - 60000);
      if (fresh.length) ips.set(ip, fresh); else ips.delete(ip);
    }
    const ip = (req.headers.get('x-forwarded-for')?.split(',')[0].trim() || 'unknown').slice(0, 128);
    const times = ips.get(ip) ?? [];
    if (global.length >= 30 || times.length >= 3 || (!ips.has(ip) && ips.size >= 1024)) return reply(429, { error: 'RateLimited' });
    times.push(time); ips.set(ip, times); global.push(time);
    const controller = new AbortController();
    const abort = () => controller.abort();
    req.signal.addEventListener('abort', abort, { once: true });
    if (req.signal.aborted) abort();
    const timer = setTimeout(abort, options.timeoutMs ?? 20000);
    try {
      const aborted = new Promise<never>((_, reject) => {
        if (controller.signal.aborted) reject(new Failure(504));
        else controller.signal.addEventListener('abort', () => reject(new Failure(504)), { once: true });
      });
      const work = async () => {
        const input = bodySchema.safeParse(await readBody(req, controller.signal));
        if (!input.success) throw new Failure(400);
        if (!(Date.parse(expiry) > now())) throw new Failure(503);
        const { session, sdp } = input.data;
        const response = await upstream('https://api.openai.com/v1/live/sessions', {
          method: 'POST', redirect: 'error', cache: 'no-store', signal: controller.signal,
          headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ session: {
            model: 'gpt-live-1', instructions: session.instructions,
            audio: { output: { voice: session.audio?.output?.voice ?? 'marin' } },
            delegation: { type: 'client' },
            client: { data_channel: {
              allowed_client_events: ['session.instructions.append', 'session.thinking.append', 'session.commentary.append', 'session.close'],
              allowed_server_events: 'all',
            } },
          }, transport: { type: 'webrtc', sdp } }),
        });
        if (!response.ok) {
          console.info(JSON.stringify({ event: 'voice_session_upstream_failed', status: response.status }));
          void response.body?.cancel().catch(() => {}); throw new Failure(502);
        }
        const parsed = answerSchema.safeParse(await response.json());
        if (!parsed.success) {
          console.info(JSON.stringify({ event: 'voice_session_upstream_shape_failed' }));
          throw new Failure(502);
        }
        return reply(201, parsed.data);
      };
      return await Promise.race([work(), aborted]);
    } catch (error) {
      // Never expose provider messages, SDP, instructions, credentials or access passes.
      return reply(error instanceof Failure ? error.status : 502, { error: 'VoiceUnavailable' });
    } finally { clearTimeout(timer); req.signal.removeEventListener('abort', abort); }
  };
}
