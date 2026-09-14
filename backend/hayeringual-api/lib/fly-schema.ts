import { z } from 'zod';

// Mirrors Runtime/Bridge/local_intent.py CODES. No motor or neural values.
export const CODES = ['STOP', 'FORWARD', 'TURN_R', 'TURN_L', 'FORWARD_R', 'FORWARD_L',
  'forward_until_concern', 'right_then_forward', 'left_then_forward',
  'nudge_right', 'nudge_left', 'continue', 'conditions', 'question', 'clarify'] as const;

export const observationSchema = z.strictObject({
  fresh: z.boolean(),
  forward: z.number().min(-1000).max(1000).nullable(),
  turn: z.number().min(-1000).max(1000).nullable(),
  bodyMovementVerified: z.literal(false),
});
export const flyStateSchema = z.strictObject({
  active: z.boolean(), candidate: z.boolean(), activeForward: z.boolean(),
  activeNudge: z.boolean(), defaultMs: z.number().int().min(1).max(120000),
  maxMs: z.number().int().min(1).max(120000),
  observation: observationSchema.optional(),
}).refine(s => s.defaultMs <= s.maxMs);
export const flyRequestSchema = z.strictObject({
  schemaVersion: z.literal(1), playerInput: z.string().trim().min(1).max(1000),
  language: z.enum(['ja', 'en']), flyState: flyStateSchema,
});
export const flyTranslationSchema = z.strictObject({
  c: z.enum(CODES), speech: z.string().max(160),
});
export const flyResponseSchema = flyTranslationSchema.extend({ schemaVersion: z.literal(1) });
export type FlyRequest = z.infer<typeof flyRequestSchema>;
export type FlyTranslation = z.infer<typeof flyTranslationSchema>;
