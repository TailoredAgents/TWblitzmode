import { planLinkChatReconnect, resolveLinkChatWebSocketBase } from '../LinkChat';

describe('resolveLinkChatWebSocketBase', () => {
  const originalWsUrl = process.env.NEXT_PUBLIC_WS_URL;
  const originalWebsocketUrl = process.env.NEXT_PUBLIC_WEBSOCKET_URL;

  afterEach(() => {
    process.env.NEXT_PUBLIC_WS_URL = originalWsUrl;
    process.env.NEXT_PUBLIC_WEBSOCKET_URL = originalWebsocketUrl;
  });

  it('prioritizes NEXT_PUBLIC_WS_URL when present', () => {
    process.env.NEXT_PUBLIC_WS_URL = 'wss://primary.example.com/socket';
    process.env.NEXT_PUBLIC_WEBSOCKET_URL = 'wss://fallback.example.com/socket';

    const result = resolveLinkChatWebSocketBase('http://api.internal:8888');
    expect(result).toBe('wss://primary.example.com/socket');
  });

  it('falls back to NEXT_PUBLIC_WEBSOCKET_URL when NEXT_PUBLIC_WS_URL is unset', () => {
    Reflect.deleteProperty(process.env, 'NEXT_PUBLIC_WS_URL');
    process.env.NEXT_PUBLIC_WEBSOCKET_URL = 'wss://fallback.example.com/socket';

    const result = resolveLinkChatWebSocketBase('http://api.internal:8888');
    expect(result).toBe('wss://fallback.example.com/socket');
  });

  it('converts http API base to ws when no explicit env vars are set', () => {
    Reflect.deleteProperty(process.env, 'NEXT_PUBLIC_WS_URL');
    Reflect.deleteProperty(process.env, 'NEXT_PUBLIC_WEBSOCKET_URL');

    const result = resolveLinkChatWebSocketBase('http://internal-api:9000');
    expect(result).toBe('ws://internal-api:9000');
  });

  it('converts https API base to wss when no explicit env vars are set', () => {
    Reflect.deleteProperty(process.env, 'NEXT_PUBLIC_WS_URL');
    Reflect.deleteProperty(process.env, 'NEXT_PUBLIC_WEBSOCKET_URL');

    const result = resolveLinkChatWebSocketBase('https://api.example.com');
    expect(result).toBe('wss://api.example.com');
  });
});

describe('planLinkChatReconnect', () => {
  it('returns retry plan with exponential backoff while under max attempts', () => {
    const plan = planLinkChatReconnect(0, 5, 1000);
    expect(plan).toEqual({ shouldRetry: true, nextAttempt: 1, delay: 1000 });

    const secondPlan = planLinkChatReconnect(1, 5, 1000);
    expect(secondPlan).toEqual({ shouldRetry: true, nextAttempt: 2, delay: 2000 });
  });

  it('stops retrying once max attempts are reached', () => {
    const plan = planLinkChatReconnect(5, 5, 1000);
    expect(plan).toEqual({ shouldRetry: false, nextAttempt: 5, delay: 0 });
  });
});
