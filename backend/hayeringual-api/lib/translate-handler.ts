import { randomUUID } from 'node:crypto';
import { infer, runtimeConfig } from './ai-client';
import { flyRequestSchema, flyTranslationSchema, type FlyRequest } from './fly-schema';
import { HttpError, jsonResponse, normalizeError, safeErrorDiagnostic } from './errors';

const MAX_BODY_BYTES = 16 * 1024;
async function readJson(req: Request, signal: AbortSignal): Promise<unknown> {
  if (req.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json')
    throw new HttpError(415, 'InvalidRequest');
  const length = req.headers.get('content-length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_BODY_BYTES))
    throw new HttpError(413, 'PayloadTooLarge');
  if (!req.body) throw new HttpError(400, 'InvalidRequest');
  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', cancel, { once: true });
  try {
    while (true) {
      signal.throwIfAborted();
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BODY_BYTES) { cancel(); throw new HttpError(413, 'PayloadTooLarge'); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
    catch { throw new HttpError(400, 'InvalidRequest'); }
  } finally { signal.removeEventListener('abort', cancel); reader.releaseLock(); }
}

type Inference = (input: FlyRequest, signal: AbortSignal) => Promise<unknown>;
type Diagnostic = { requestId: string; model: string; latencyMs: number; status: number; success: boolean; timeout: boolean; errorKind?: string; upstreamStatus?: number; reasonCode?: string };
export function createTranslateHandler(inference: Inference = infer,
  log: (event: Diagnostic) => void = event => {
    if (process.env.HAYERINGUAL_LOG_LEVEL !== 'off') console.info(JSON.stringify(event));
  }) {
  return async (req: Request): Promise<Response> => {
    const start = performance.now(), requestId = randomUUID();
    let status = 503, model = 'unavailable', timedOut = false;
    let errorDiagnostic: ReturnType<typeof safeErrorDiagnostic> | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const abort = () => controller.abort();
    req.signal.addEventListener('abort', abort, { once: true });
    if (req.signal.aborted) abort();
    try {
      const config = runtimeConfig(); model = config.model;
      timer = setTimeout(() => { timedOut = true; controller.abort(); }, config.timeoutMs);
      const aborted = new Promise<never>((_, reject) => {
        const fail = () => reject(new HttpError(503, 'CloudUnavailable'));
        if (controller.signal.aborted) fail();
        else controller.signal.addEventListener('abort', fail, { once: true });
      });
      const work = async () => {
        const parsed = flyRequestSchema.safeParse(await readJson(req, controller.signal));
        if (!parsed.success) throw new HttpError(400, 'InvalidRequest');
        const output = flyTranslationSchema.safeParse(await inference(parsed.data, controller.signal));
        if (!output.success) throw new HttpError(503, 'CloudUnavailable');
        return output.data;
      };
      const output = await Promise.race([work(), aborted]);
      status = 200;
      return jsonResponse({ schemaVersion: 1, ...output });
    } catch (error) {
      errorDiagnostic = safeErrorDiagnostic(error);
      const normalized = normalizeError(error); status = normalized.status;
      return jsonResponse({ schemaVersion: 1, error: normalized.code }, status);
    } finally {
      clearTimeout(timer); req.signal.removeEventListener('abort', abort);
      log({ requestId, model, latencyMs: Math.round(performance.now() - start), status,
        success: status === 200, timeout: timedOut, ...errorDiagnostic });
    }
  };
}
