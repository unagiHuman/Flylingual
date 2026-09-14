import { generateText, Output } from 'ai';
import { flyTranslationSchema, type FlyRequest } from './fly-schema';
import { FLY_PROMPT } from './fly-prompt';

export function runtimeConfig(env: Record<string, string | undefined> = process.env) {
  const integer = (name: string, fallback: number, min: number, max: number) => {
    const raw = env[name];
    const n = raw === undefined || raw === '' ? fallback : Number(raw);
    if (!Number.isInteger(n) || n < min || n > max) throw new Error('InvalidRuntimeConfig');
    return n;
  };
  if (env.HAYERINGUAL_REASONING && env.HAYERINGUAL_REASONING !== 'minimal')
    throw new Error('InvalidRuntimeConfig');
  const model = env.HAYERINGUAL_LLM_MODEL || 'google/gemini-3.5-flash-lite';
  if (!/^[a-z0-9][a-z0-9._-]*\/[a-zA-Z0-9][a-zA-Z0-9._:-]*$/.test(model))
    throw new Error('InvalidRuntimeConfig');
  return { model, reasoning: 'minimal' as const,
    maxOutputTokens: integer('HAYERINGUAL_MAX_OUTPUT_TOKENS', 96, 32, 128),
    timeoutMs: integer('HAYERINGUAL_TIMEOUT_MS', 4000, 100, 4000) };
}

export async function infer(input: FlyRequest, signal: AbortSignal): Promise<unknown> {
  const config = runtimeConfig();
  const { output } = await generateText({
    model: config.model, system: FLY_PROMPT, prompt: JSON.stringify(input),
    reasoning: config.reasoning, maxOutputTokens: config.maxOutputTokens,
    maxRetries: 0, abortSignal: signal,
    providerOptions: {
      gateway: { sort: 'ttft' },
      google: { thinkingConfig: { thinkingLevel: 'minimal', includeThoughts: false } },
    },
    output: Output.object({ schema: flyTranslationSchema }),
  });
  return output;
}
