// WebSocket Service for Real-time Updates
// Migrated to native WebSocket transport to align with FastAPI backend

import type { WebSocketEventType, WebSocketMessage } from '../types';
import { getAccessToken } from '../lib/authToken';
import { normalizeWebSocketBaseUrl } from '../lib/websocketUrl';

export type WebSocketEventHandler = (data: unknown) => void;

type ConnectionContext = {
  tenantId?: number | string;
  userId?: number | string;
};

class WebSocketService {
  private socket: WebSocket | null = null;
  private isConnected = false;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 5;
  private readonly eventHandlers: Map<string, WebSocketEventHandler[]> = new Map();
  private readonly pendingMessages: Array<Record<string, unknown>> = [];
  private readonly joinedRooms: Set<string> = new Set();
  private tenantId?: string;
  private userId?: string;
  private sessionId?: string;
  private manualClose = false;
  private reconnectRequested = false;

  connect(context: ConnectionContext = {}): void {
    if (typeof window === 'undefined') {
      return;
    }

    // Skip WebSocket connection if disabled (for testing/development)
    if (process.env.NEXT_PUBLIC_DISABLE_WEBSOCKET === 'true') {
      console.info('[WebSocket] Connections disabled via NEXT_PUBLIC_DISABLE_WEBSOCKET');
      return;
    }

    if (context.tenantId !== undefined) {
      this.tenantId = String(context.tenantId);
    }
    if (context.userId !== undefined) {
      this.userId = String(context.userId);
    }

    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.sessionId = this.sessionId ?? this.loadOrCreateSessionId();

    const url = this.buildConnectionUrl();

    try {
      this.manualClose = false;
      this.reconnectRequested = false;
      this.socket = new WebSocket(url);
    } catch (error) {
      console.error('Failed to establish WebSocket connection', error);
      this.emit('connection_error', { error: error instanceof Error ? error.message : String(error) });
      return;
    }

    this.setupNativeHandlers();
  }

  private loadOrCreateSessionId(): string {
    if (typeof window === 'undefined') {
      return crypto.randomUUID();
    }

    const storageKey = 'tallwave_ws_session_id';
    try {
      const existing = window.sessionStorage.getItem(storageKey);
      if (existing) {
        return existing;
      }
      const newId = crypto.randomUUID();
      window.sessionStorage.setItem(storageKey, newId);
      return newId;
    } catch {
      return crypto.randomUUID();
    }
  }

  private buildConnectionUrl(): string {
    const base =
      process.env.NEXT_PUBLIC_WEBSOCKET_URL ??
      process.env.NEXT_PUBLIC_API_URL ??
      'http://localhost:8888';

    const isBrowser = typeof window !== 'undefined';
    const preferSecure = isBrowser
      ? window.location?.protocol === 'https:'
      : process.env.NODE_ENV === 'production';

    let fallbackHost: string | undefined;
    if (typeof window !== 'undefined') {
      const locationHost = window.location?.host;
      if (locationHost) {
        const protocol = preferSecure ? 'https' : 'http';
        fallbackHost = `${protocol}://${locationHost}`;
      }
    }

    const url = normalizeWebSocketBaseUrl(base, {
      preferSecure,
      ...(fallbackHost && { fallbackHost }),
    });

    const template = process.env.NEXT_PUBLIC_WEBSOCKET_PATH ?? '/ws/agent_chat';
    const tenantSegment = encodeURIComponent(this.tenantId ?? 'default');
    const userSegment = this.userId ? encodeURIComponent(this.userId) : '';
    const sessionSegment = this.sessionId ? encodeURIComponent(this.sessionId) : '';

    let path = template;
    if (path.includes('{tenantId}')) {
      path = path.replace('{tenantId}', tenantSegment);
    }

    if (path.includes('{userId?}')) {
      const replacement = userSegment ? `/${userSegment}` : '';
      path = path.replace('{userId?}', replacement);
    }

    if (path.includes('{userId}')) {
      const safeUserSegment = userSegment ?? '';
      path = path.replace('{userId}', safeUserSegment);
    }

    if (path.includes('{sessionId}')) {
      const sessionReplacement =
        sessionSegment && sessionSegment.length > 0 ? sessionSegment : tenantSegment;
      path = path.replace('{sessionId}', sessionReplacement);
    }

    if (!path.startsWith('/')) {
      path = `/${path}`;
    }

    path = path.replace(/\/{2,}/g, '/');

    url.pathname = path;

    if (this.sessionId) {
      url.searchParams.set('session_id', this.sessionId);
    }

    url.searchParams.set('tenant_id', this.tenantId ?? 'default');

    if (this.userId) {
      url.searchParams.set('user_id', this.userId);
    }

    const authToken = this.resolveAuthToken();
    if (authToken) {
      url.searchParams.set('token', authToken);
    }

    return url.toString();
  }

  private resolveAuthToken(): string | undefined {
    const token = getAccessToken();
    return token ?? undefined;
  }

  private setupNativeHandlers(): void {
    if (!this.socket) {
      return;
    }

    this.socket.onopen = () => {
      this.isConnected = true;
      this.reconnectAttempts = 0;
      this.manualClose = false;
      this.reconnectRequested = false;
      this.emit('connect', { sessionId: this.sessionId });
      this.emit('connection_status', { connected: true });

      const token = this.resolveAuthToken();
      if (token) {
        const authPayload: Record<string, unknown> = { type: 'authenticate', token };
        if (this.tenantId) {
          authPayload.tenant_id = this.tenantId;
        }
        if (this.userId) {
          authPayload.user_id = this.userId;
        }
        this.sendJson(authPayload);
      }

      // Flush any queued subscriptions or messages
      this.joinedRooms.forEach((room) => {
        this.sendJson({ type: 'subscribe', channel: room, channels: [room] });
      });
      this.flushPendingMessages();
    };

    this.socket.onclose = (event) => {
      const wasManual = this.manualClose;
      const shouldRetry = !wasManual && this.reconnectAttempts < this.maxReconnectAttempts;
      const plannedReconnect = this.reconnectRequested;

      this.isConnected = false;
      this.socket = null;
      this.emit('disconnect', { code: event.code, reason: event.reason });
      this.emit('connection_status', { connected: false, code: event.code, reason: event.reason });

      if (plannedReconnect) {
        this.reconnectRequested = false;
        this.connect();
        return;
      }

      if (shouldRetry) {
        this.attemptReconnect();
      }
    };

    this.socket.onerror = (error) => {
      console.error('WebSocket error', error);
      this.emit('connection_error', { error });
    };

    this.socket.onmessage = (event) => {
      try {
        const parsed: WebSocketMessage | Record<string, unknown> = JSON.parse(event.data);
        const typedMessage = parsed as Partial<WebSocketMessage> & Record<string, unknown>;
        const rawEventType = [typedMessage.type, typedMessage.event].find(
          (value): value is WebSocketEventType => typeof value === 'string' && value.length > 0
        );

        if (rawEventType) {
          const payload =
            (parsed as WebSocketMessage).data ??
            (typedMessage.payload as unknown) ??
            (typedMessage.approval as unknown) ??
            (typedMessage.workflow as unknown) ??
            parsed;
          this.emit(rawEventType, payload);
        }

        this.emit('message', parsed);
      } catch (err) {
        console.error('Failed to parse WebSocket payload', err);
        this.emit('connection_error', { error: err instanceof Error ? err.message : String(err) });
      }
    };
  }

  private flushPendingMessages(): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }

    while (this.pendingMessages.length > 0) {
      const payload = this.pendingMessages.shift();
      if (payload) {
        this.socket.send(JSON.stringify(payload));
      }
    }
  }

  private sendJson(payload: Record<string, unknown>): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    } else {
      this.pendingMessages.push(payload);
    }
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.emit('connection_failed', { attempts: this.reconnectAttempts });
      return;
    }

    this.reconnectAttempts += 1;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 30000);

    setTimeout(() => {
      if (!this.isConnected) {
        this.connect();
      }
    }, delay);
  }

  disconnect(): void {
    this.manualClose = true;
    this.reconnectRequested = false;

    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }

    this.isConnected = false;
    this.eventHandlers.clear();
    this.joinedRooms.clear();
    this.pendingMessages.length = 0;
  }

  getJoinedRoomsSnapshot(): ReadonlyArray<string> {
    return Array.from(this.joinedRooms);
  }

  clearJoinedRooms(): void {
    this.joinedRooms.clear();
  }

  getPendingMessagesSnapshot(): ReadonlyArray<Record<string, unknown>> {
    return [...this.pendingMessages];
  }

  clearPendingMessages(): void {
    this.pendingMessages.length = 0;
  }

  setUserContext(userId?: number | string, tenantId?: number | string): void {
    const normalizedUser = userId !== undefined ? String(userId) : undefined;
    const normalizedTenant = tenantId !== undefined ? String(tenantId) : undefined;

    const tenantChanged = normalizedTenant !== undefined && normalizedTenant !== this.tenantId;
    const userChanged = normalizedUser !== undefined && normalizedUser !== this.userId;

    if (normalizedUser !== undefined) {
      this.userId = normalizedUser;
    }
    if (normalizedTenant !== undefined) {
      this.tenantId = normalizedTenant;
    }

    if (this.socket && (tenantChanged || userChanged)) {
      this.reconnectRequested = true;
      this.socket.close();
    }
  }

  // Event subscription helpers
  on(event: string, handler: WebSocketEventHandler): void {
    const existingHandlers = this.eventHandlers.get(event);
    if (existingHandlers) {
      existingHandlers.push(handler);
      return;
    }
    this.eventHandlers.set(event, [handler]);
  }

  off(event: string, handler: WebSocketEventHandler): void {
    const handlers = this.eventHandlers.get(event);
    if (!handlers) {
      return;
    }
    const index = handlers.indexOf(handler);
    if (index >= 0) {
      handlers.splice(index, 1);
    }
  }

  private emit(event: string, data: unknown): void {
    const handlers = this.eventHandlers.get(event);
    if (!handlers) {
      return;
    }
    handlers.forEach((handler) => {
      try {
        handler(data);
      } catch (error) {
        console.error(`Error in WebSocket handler for ${event}`, error);
      }
    });
  }

  // Publish messages to backend
  send(event: string, data?: unknown): void {
    this.sendJson({ type: event, data });
  }

  sendMessage(content: string): void {
    this.sendJson({ type: 'message', content });
  }

  // Room helpers (converted to lightweight subscription semantics)
  joinOrganizationRoom(organizationId: number | string): void {
    const orgKey = String(organizationId);
    const room = `org:${orgKey}`;
    this.tenantId = orgKey;
    this.joinedRooms.add(room);
    this.sendJson({ type: 'subscribe', channel: room, channels: [room] });

    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING) &&
      !this.reconnectRequested
    ) {
      this.reconnectRequested = true;
      this.socket.close();
    }
  }

  joinApprovalRoom(tenantId?: number | string): void {
    const tenantKey = tenantId !== undefined ? String(tenantId) : this.tenantId ?? 'default';
    const room = `approval:${tenantKey}`;
    this.joinedRooms.add(room);
    this.sendJson({ type: 'subscribe', channel: room, channels: [room] });
  }

  joinCookieRoom(tenantId?: number | string): void {
    const tenantKey = tenantId !== undefined ? String(tenantId) : this.tenantId ?? 'default';
    const room = `cookie:${tenantKey}`;
    this.joinedRooms.add(room);
    this.sendJson({ type: 'subscribe', channel: room, channels: [room] });
  }

  joinWorkflowRoom(workflowId: string): void {
    const room = `workflow:${workflowId}`;
    this.joinedRooms.add(room);
    this.sendJson({ type: 'subscribe', channel: room, channels: [room] });
  }

  leaveOrganizationRoom(organizationId: number): void {
    const room = `org:${organizationId}`;
    this.joinedRooms.delete(room);
    this.sendJson({ type: 'unsubscribe', channel: room, channels: [room] });
  }

  leaveApprovalRoom(tenantId?: number | string): void {
    const tenantKey = tenantId !== undefined ? String(tenantId) : this.tenantId ?? 'default';
    const room = `approval:${tenantKey}`;
    this.joinedRooms.delete(room);
    this.sendJson({ type: 'unsubscribe', channel: room, channels: [room] });
  }

  leaveCookieRoom(tenantId?: number | string): void {
    const tenantKey = tenantId !== undefined ? String(tenantId) : this.tenantId ?? 'default';
    const room = `cookie:${tenantKey}`;
    this.joinedRooms.delete(room);
    this.sendJson({ type: 'unsubscribe', channel: room, channels: [room] });
  }

  leaveWorkflowRoom(workflowId: string): void {
    const room = `workflow:${workflowId}`;
    this.joinedRooms.delete(room);
    this.sendJson({ type: 'unsubscribe', channel: room, channels: [room] });
  }

  isConnectedToServer(): boolean {
    return this.isConnected && this.socket?.readyState === WebSocket.OPEN;
  }

  getConnectionState(): { connected: boolean; attempts: number } {
    return {
      connected: this.isConnected,
      attempts: this.reconnectAttempts,
    };
  }
}

const webSocketService = new WebSocketService();
export default webSocketService;
