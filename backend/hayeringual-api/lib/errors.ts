export class HttpError extends Error {
  constructor(public status: number, public code: string) { super(code); }
}
export function normalizeError(error: unknown): HttpError {
  if (error instanceof HttpError) return error;
  // Provider messages, response bodies and credentials never cross the boundary.
  return new HttpError(503, 'CloudUnavailable');
}
export function jsonResponse(value: unknown, status = 200): Response {
  return Response.json(value, { status, headers: { 'Cache-Control': 'no-store' } });
}
import { APICallError, NoObjectGeneratedError, NoOutputGeneratedError,
  LoadAPIKeyError, UnsupportedFunctionalityError, TypeValidationError,
  JSONParseError, InvalidResponseDataError, NoSuchModelError } from 'ai';
import { GatewayError } from '@ai-sdk/gateway';

function gatewayReason(error: GatewayError): string {
  // Inspect a bounded error chain in memory; only fixed categories may escape.
  let current: unknown = error;
  let text = '';
  for (let depth = 0; depth < 3 && current instanceof Error; depth++) {
    text += ' ' + String(current.message).slice(0, 4096).toLowerCase();
    current = current.cause;
  }
  const patterns: [string, RegExp][] = [
    ['DeploymentProtection', /deployment protection|vercel authentication|deployment.*protected|protection bypass/],
    ['BillingOrCredits', /billing|payment|credit|insufficient funds|budget|balance|spend limit/],
    ['RegionRestriction', /unsupported (?:country|region)|region.*(?:restrict|not available)|country.*(?:restrict|not supported)|geographic/],
    ['ModelUnavailable', /model.*(?:not found|not available|unsupported|does not exist)|no available provider/],
    ['AuthenticationOrPermission', /authenticat|invalid.{0,12}(?:api.?key|token)|api.?key.*(?:invalid|expired|missing)|permission|forbidden|access denied|unauthorized/],
  ];
  return patterns.find(([, pattern]) => pattern.test(text))?.[0] ?? 'Unclassified';
}

export function safeErrorDiagnostic(error: unknown): { errorKind: string; upstreamStatus?: number; reasonCode?: string } {
  if (GatewayError.isInstance(error)) {
    const kinds = new Set(['GatewayAuthenticationError', 'GatewayFailedDependencyError',
      'GatewayForbiddenError', 'GatewayInternalServerError', 'GatewayInvalidRequestError',
      'GatewayModelNotFoundError', 'GatewayNotFoundError', 'GatewayRateLimitError', 'GatewayResponseError']);
    return { errorKind: kinds.has(error.name) ? error.name : 'GatewayError', reasonCode: gatewayReason(error),
      ...(Number.isInteger(error.statusCode) && error.statusCode >= 100 && error.statusCode <= 599
        ? { upstreamStatus: error.statusCode } : {}) };
  }
  if (APICallError.isInstance(error)) {
    const status = error.statusCode;
    return { errorKind: 'APICallError', ...(Number.isInteger(status) && status! >= 100 && status! <= 599
      ? { upstreamStatus: status } : {}) };
  }
  for (const [kind, matches] of [
    ['NoObjectGeneratedError', NoObjectGeneratedError.isInstance],
    ['NoOutputGeneratedError', NoOutputGeneratedError.isInstance],
    ['LoadAPIKeyError', LoadAPIKeyError.isInstance],
    ['UnsupportedFunctionalityError', UnsupportedFunctionalityError.isInstance],
    ['TypeValidationError', TypeValidationError.isInstance],
    ['JSONParseError', JSONParseError.isInstance],
    ['InvalidResponseDataError', InvalidResponseDataError.isInstance],
    ['NoSuchModelError', NoSuchModelError.isInstance],
  ] as const) {
    if (matches(error)) return { errorKind: kind };
  }
  return { errorKind: error instanceof HttpError ? 'RequestOrValidationError' : 'UnknownError' };
}
