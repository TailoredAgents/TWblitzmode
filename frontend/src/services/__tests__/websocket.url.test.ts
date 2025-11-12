import webSocketService from '../websocket';
import { clearAccessToken, setAccessToken } from '../../lib/authToken';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static lastUrl: string | null = null;

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  public readyState = MockWebSocket.CONNECTING;
  public onopen: ((event: Event) => void) | null = null;
  public onclose: ((event: CloseEvent) => void) | null = null;
  public onerror: ((event: Event) => void) | null = null;
  public onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
    MockWebSocket.lastUrl = url;
  }

  send(): void {
    // no-op in tests
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose({
        code: 1000,
        reason: 'closed',
      } as CloseEvent);
    }
  }
}

describe('WebSocketService environment URL resolution', () => {
  const OriginalWebSocket = global.WebSocket;

  beforeEach(() => {
    jest.restoreAllMocks();
    MockWebSocket.instances = [];
    MockWebSocket.lastUrl = null;
    webSocketService.disconnect();
    setAccessToken('memory-token');

    delete process.env.NEXT_PUBLIC_WEBSOCKET_URL;
    delete process.env.NEXT_PUBLIC_WEBSOCKET_PATH;
    delete process.env.NEXT_PUBLIC_API_URL;

    // @ts-expect-error - assign mock WebSocket implementation
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    webSocketService.disconnect();
    clearAccessToken();
    global.WebSocket = OriginalWebSocket;
    delete process.env.NEXT_PUBLIC_WEBSOCKET_URL;
    delete process.env.NEXT_PUBLIC_WEBSOCKET_PATH;
    delete process.env.NEXT_PUBLIC_API_URL;
  });

  it('builds tenant-scoped secure websocket URL from runtime environment variables', () => {
    process.env.NEXT_PUBLIC_WEBSOCKET_URL = 'https://realtime.example.com/base';
    process.env.NEXT_PUBLIC_WEBSOCKET_PATH = '/agent-stream/{tenantId}/{userId?}/channel';

    webSocketService.connect({ tenantId: 'tenant-A', userId: 'user-9' });

    expect(MockWebSocket.instances).toHaveLength(1);
    const urlString = MockWebSocket.lastUrl;
    expect(urlString).toBeTruthy();

    const url = new URL(urlString ?? '');
    expect(url.protocol).toBe('wss:');
    expect(url.pathname).toBe('/agent-stream/tenant-A/user-9/channel');
    expect(url.searchParams.get('tenant_id')).toBe('tenant-A');
    expect(url.searchParams.get('user_id')).toBe('user-9');
    expect(url.searchParams.get('token')).toBeNull();
    expect(url.searchParams.get('session_id')).toBeTruthy();
  });

  it('falls back to API URL when websocket base is not configured', () => {
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8888';
    process.env.NEXT_PUBLIC_WEBSOCKET_PATH = 'ws/agent_chat/{tenantId}';

    webSocketService.connect({ tenantId: '42' });

    expect(MockWebSocket.instances).toHaveLength(1);
    const urlString = MockWebSocket.lastUrl;
    expect(urlString).toBeTruthy();

    const url = new URL(urlString ?? '');
    expect(url.protocol).toBe('ws:');
    expect(url.pathname).toBe('/ws/agent_chat/42');
    expect(url.searchParams.get('tenant_id')).toBe('42');
    expect(url.searchParams.get('token')).toBeNull();
  });
});
