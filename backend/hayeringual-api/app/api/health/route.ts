import { jsonResponse } from '../../../lib/errors';
export const runtime = 'nodejs';
export function GET() {
  return jsonResponse({ ok: true, service: 'hayeringual-api', version: '1' });
}
