import { flyResponseSchema } from '../lib/fly-schema';

// Real endpoint only. No injected inference, SDK key or fabricated successful samples.
const rawUrl = process.argv[2];
if (!rawUrl) throw new Error('Usage: npx tsx scripts/benchmark.ts https://YOUR-BACKEND [count>=20]');
const base = new URL(rawUrl);
if (base.username || base.password || base.search || base.hash ||
    !(base.protocol === 'https:' || base.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)))
  throw new Error('Use HTTPS backend URL, or localhost HTTP, without credentials/query/hash.');
const count = process.argv[3] === undefined ? 20 : Number(process.argv[3]);
if (!Number.isInteger(count) || count < 20 || count > 100) throw new Error('Count must be 20..100.');
const health = await fetch(new URL('/api/health', base), { signal: AbortSignal.timeout(5000) });
const healthJson = await health.json();
if (!health.ok || healthJson?.ok !== true || healthJson?.service !== 'hayeringual-api' || healthJson?.version !== '1')
  throw new Error('Health check failed.');
const prompts = [
  ['ja', '少し右を向いて'], ['ja', 'そのまま'], ['ja', '今どういう状態？'],
  ['ja', 'こんにちは'], ['en', 'Turn a little left'], ['en', 'How are you?'],
  ['ja', '危ないなら止まって'], ['en', 'Move forward for two seconds'],
] as const;
const samples: { index: number; elapsedMs: number; status: number | null; success: boolean; error?: string }[] = [];
for (let i = 0; i < count; i++) {
  const [language, playerInput] = prompts[i % prompts.length];
  const start = performance.now();
  let status: number | null = null, success = false, error: string | undefined;
  try {
    const response = await fetch(new URL('/api/fly/translate', base), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(5000),
      body: JSON.stringify({ schemaVersion: 1, playerInput, language,
        flyState: { active: false, candidate: false, activeForward: false,
          activeNudge: false, defaultMs: 1000, maxMs: 120000 } }),
    });
    status = response.status;
    success = response.ok && flyResponseSchema.safeParse(await response.json()).success;
    if (!success) error = response.ok ? 'InvalidResponse' : 'HttpFailure';
  } catch { error = 'NetworkOrTimeout'; }
  samples.push({ index: i + 1, elapsedMs: Math.round(performance.now() - start), status, success, ...(error ? { error } : {}) });
}
function stats(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return null;
  const percentile = (p: number) => sorted[Math.ceil(p * sorted.length) - 1];
  return { count: sorted.length, p50Ms: percentile(.5), p95Ms: percentile(.95), minMs: sorted[0], maxMs: sorted.at(-1) };
}
console.log(JSON.stringify({ timestamp: new Date().toISOString(), endpoint: base.origin,
  count, errorCount: samples.filter(s => !s.success).length,
  allRequests: stats(samples.map(s => s.elapsedMs)),
  successfulRequests: stats(samples.filter(s => s.success).map(s => s.elapsedMs)), samples }, null, 2));
if (samples.some(s => !s.success)) process.exitCode = 1;
