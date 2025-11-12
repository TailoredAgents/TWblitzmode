import { normalizeWebSocketBaseUrl } from '../websocketUrl';

describe('normalizeWebSocketBaseUrl', () => {
  it('infers wss for production hosts without an explicit protocol', () => {
    const result = normalizeWebSocketBaseUrl('api.vouchlink.ai', { preferSecure: true });
    expect(result.toString()).toBe('wss://api.vouchlink.ai/');
  });

  it('retains secure websocket protocols when already specified', () => {
    const result = normalizeWebSocketBaseUrl('wss://secure.example.com/socket', { preferSecure: true });
    expect(result.toString()).toBe('wss://secure.example.com/socket');
  });

  it('falls back to ws for localhost when insecure is allowed', () => {
    const result = normalizeWebSocketBaseUrl('localhost:8080', { preferSecure: false });
    expect(result.toString()).toBe('ws://localhost:8080/');
  });
});
