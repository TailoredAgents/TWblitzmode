const PROTOCOL_PATTERN = /^[a-z][a-z0-9+.-]*:\/\//i;

export interface NormalizeWebSocketOptions {
  preferSecure?: boolean;
  fallbackHost?: string;
}

const DEFAULT_FALLBACK_HTTP = 'http://localhost:8888';
const DEFAULT_FALLBACK_HTTPS = 'https://localhost';

function ensureWithProtocol(value: string | undefined, preferSecure: boolean, fallback: string): string {
  const candidate = (value ?? '').trim();
  if (!candidate) {
    return fallback;
  }
  if (PROTOCOL_PATTERN.test(candidate)) {
    return candidate;
  }
  const scheme = preferSecure ? 'https' : 'http';
  return `${scheme}://${candidate}`;
}

/**
 * Normalize a WebSocket base URL by inferring secure protocols when required and
 * guaranteeing the output can be safely passed to the native WebSocket constructor.
 */
export function normalizeWebSocketBaseUrl(
  raw: string | undefined,
  options: NormalizeWebSocketOptions = {},
): URL {
  const preferSecure = options.preferSecure ?? false;
  const fallback = options.fallbackHost
    ? ensureWithProtocol(options.fallbackHost, preferSecure, options.fallbackHost)
    : ensureWithProtocol(
        preferSecure ? DEFAULT_FALLBACK_HTTPS : DEFAULT_FALLBACK_HTTP,
        preferSecure,
        preferSecure ? DEFAULT_FALLBACK_HTTPS : DEFAULT_FALLBACK_HTTP,
      );

  const candidate = ensureWithProtocol(raw, preferSecure, fallback);

  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    url = new URL(fallback);
  }

  if (!['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol)) {
    url.protocol = preferSecure ? 'https:' : 'http:';
  }

  if (preferSecure && url.protocol === 'http:') {
    url.protocol = 'https:';
  }

  if (url.protocol === 'http:') {
    url.protocol = 'ws:';
  } else if (url.protocol === 'https:') {
    url.protocol = 'wss:';
  } else if (!['ws:', 'wss:'].includes(url.protocol)) {
    url.protocol = preferSecure ? 'wss:' : 'ws:';
  }

  return url;
}
