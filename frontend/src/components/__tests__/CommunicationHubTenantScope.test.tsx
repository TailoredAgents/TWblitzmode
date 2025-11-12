import React from 'react';
import { render, waitFor } from '@testing-library/react';
import CommunicationHub from '../CommunicationHub';

jest.mock('../../services/api', () => {
  const approvalsSummary = {
    level_counts: {
      debug: 0,
      info: 0,
      warning: 0,
      error: 0,
      critical: 0,
    },
    top_event_types: [],
    active_agents: [],
  };

  return {
    apiService: {
      getCommunicationConversations: jest.fn().mockResolvedValue({ data: [] }),
      getCommunicationAgents: jest.fn().mockResolvedValue({ data: [] }),
      getApprovalRequests: jest.fn().mockResolvedValue({ data: [] }),
      getAgentEvents: jest.fn().mockResolvedValue({ data: [] }),
      getAgentEventsSummary: jest.fn().mockResolvedValue({ data: approvalsSummary }),
      sendCommunicationMessage: jest.fn().mockResolvedValue({ data: null }),
      makeApprovalDecision: jest.fn().mockResolvedValue({ data: null }),
      createCommunicationConversation: jest.fn().mockResolvedValue({ data: null }),
      retryCorporateWorkflow: jest.fn().mockResolvedValue({ data: null }),
    },
  };
});

jest.mock('../ui/ToastContainer', () => ({
  useToastActions: () => ({
    success: jest.fn(),
    error: jest.fn(),
  }),
}));

jest.mock('../../services/websocket', () => ({
  __esModule: true,
  default: {
    on: jest.fn(),
    off: jest.fn(),
  },
}));

// eslint-disable-next-line import/first
import { apiService } from '../../services/api';

const getApprovalRequestsMock = apiService.getApprovalRequests as jest.Mock;

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  public readyState = MockWebSocket.CONNECTING;
  public onmessage: ((event: MessageEvent) => void) | null = null;
  public onclose: ((event: CloseEvent) => void) | null = null;
  public url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
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

  send(): void {
    // noop for tests
  }
}

describe('CommunicationHub tenant scoping', () => {
  const OriginalWebSocket = global.WebSocket;

  beforeEach(() => {
    jest.clearAllMocks();
    MockWebSocket.instances = [];
    // @ts-expect-error - mock WebSocket for JSDOM environment
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    global.WebSocket = OriginalWebSocket;
  });

  it('requests approvals using the tenant identifier when provided', async () => {
    render(
      <CommunicationHub
        organizationId="org-001"
        tenantId="tenant-555"
        userId="user-007"
        currentUser={{ id: 'user-007', email: 'user@example.com', name: 'Tenant User' }}
      />,
    );

    await waitFor(() => {
      expect(getApprovalRequestsMock).toHaveBeenCalledTimes(1);
    });

    const [params] = getApprovalRequestsMock.mock.calls[0] ?? [];
    expect(params).toBeDefined();
    expect(params.tenantId).toBe('tenant-555');
  });

  it('opens the events websocket scoped to the tenant context', async () => {
    render(
      <CommunicationHub
        organizationId="org-100"
        tenantId="tenant-ctx"
        userId="user-007"
        currentUser={{ id: 'user-007', email: 'ctx@example.com', name: 'Ctx User' }}
      />,
    );

    await waitFor(() => {
      expect(MockWebSocket.instances.length).toBeGreaterThan(0);
    });

    const socket = MockWebSocket.instances[0];
    expect(socket).toBeDefined();

    const url = new URL(socket.url);
    expect(url.searchParams.get('tenant_id')).toBe('tenant-ctx');
    expect(url.searchParams.get('organization_id')).toBe('org-100');
  });
});
