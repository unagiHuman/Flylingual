import { createVoiceSessionHandler } from '../../../../../lib/voice-session-handler';

export const runtime = 'nodejs';
export const maxDuration = 30;
export const POST = createVoiceSessionHandler();
