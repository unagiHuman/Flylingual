# Hayeringual translation backend

Next.js App Router Node runtime, Node >=22 (verified on 24.13.1). Set Vercel project Root Directory to `backend/hayeringual-api`. Install with `npm ci`; run `npm test`, `npm run typecheck`, `npm run build`. `npm run dev` binds localhost only.

Copy `.env.example` to an ignored `.env.local` for local development. Supply a dedicated Judge Gateway key through Vercel environment settings for deployment. Never put keys in Unity/configuration files, command arguments or Git. Use a separately scoped Preview key. Set the Judge key budget/expiry in Gateway before distributing a public URL. Environment changes require redeployment.

`GET /api/health` returns only `{ "ok": true, "service": "hayeringual-api", "version": "1" }` and is not a model readiness probe.

`POST /api/fly/translate` accepts `application/json`:

```json
{
  "schemaVersion": 1,
  "playerInput": "右に進んで",
  "language": "ja",
  "flyState": {
    "active": false,
    "candidate": false,
    "activeForward": false,
    "activeNudge": false,
    "defaultMs": 1000,
    "maxMs": 120000
  }
}
```

Successful response: `{ "schemaVersion": 1, "c": "right_then_forward", "speech": "右だね。" }`. `c` exactly mirrors existing Bridge `local_intent.CODES`; the enum parity test checks the Python source. Speech is an interpretation or short answer, never evidence of completed movement. Command context is **not** sensory/neural/body state. No raw neuron data is sent. Bridge still grounds quantities and validates intent before Brain execution.

Unknown properties are rejected, input is at most 1000 characters and the streamed request body is bounded to 16 KiB even without Content-Length. Output is schema checked and speech bounded to 160 characters. Invalid requests return 400/413/415. All upstream failures (including Gateway 402), invalid model output, timeout and client cancellation return HTTP 503 `{ "schemaVersion": 1, "error": "CloudUnavailable" }`. Client must use its existing safe fallback and must not replay old actions. Response cache is disabled.

Default model `google/gemini-3.5-flash-lite`, reasoning `minimal`, 96 output tokens, 4000 ms hard deadline, zero SDK retries, Gateway `sort: ttft` without provider pinning. Model is configurable via `HAYERINGUAL_LLM_MODEL`; output tokens may be 32–128 and timeout 100–4000 ms. Invalid environment configuration fails closed. `HAYERINGUAL_LOG_LEVEL=off` disables diagnostics; default logs contain only generated request ID, selected model, latency, status, success and timeout. No request text, state, provider error body or credentials are logged.

Installed typings verified: `ai@7.0.99` supports top-level `reasoning`, `Output.object`, `abortSignal` and `maxRetries`; Gateway typings accept `sort: 'ttft'`. Dependencies are pinned in `package-lock.json`. References: [AI SDK generateText](https://ai-sdk.dev/docs/reference/ai-sdk-core/generate-text), [Gateway provider options](https://vercel.com/docs/ai-gateway/models-and-providers/provider-options).

Unit tests use injected inference solely to verify HTTP/schema/failure boundaries. They are not evidence of real Gateway latency, language quality, real Brain/Unity integration or clean-machine play. Those require deployment credentials and the integration test procedures in the repository's Judge runtime document.

Optional `flyState.observation` is `{ fresh: boolean, forward: number|null, turn: number|null, bodyMovementVerified: false }`. Numbers must be finite within -1000..1000. These are neural decoder outputs, not physical movement confirmation. Stale or null values are not current observations; no raw neural data is accepted.

After deploying, run `npx tsx scripts/benchmark.ts https://YOUR-BACKEND 20` to measure real HTTP requests. The script checks health and every successful response schema, reports P50/P95/min/max separately for all and successful requests, records failures, and exits nonzero for any failure. It sends 20–100 bounded requests sequentially and incurs normal Gateway usage. It does not test Brain/physical play or claim latency when no successful requests exist. No benchmark has been run against a deployed Gateway in this implementation pass.
