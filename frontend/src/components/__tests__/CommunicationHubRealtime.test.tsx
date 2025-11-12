import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import CommunicationHub from '../CommunicationHub';

jest.mock('../../services/api', () => ({
  apiService: {
    getCommunicationConversations: jest.fn().mockResolvedValue({ data: [] }),
    getCommunicationAgents: jest.fn().mockResolvedValue({ data: [] }),
    getApprovalRequests: jest.fn().mockResolvedValue({ data: [] }),
    getAgentEvents: jest.fn().mockResolvedValue({ data: [] }),
    getAgentEventsSummary: jest
      .fn()
      .mockResolvedValue({
        data: {
          level_counts: {
            debug: 0,
            info: 0,
            warning: 0,
            error: 0,
            critical: 0,
          },
          top_event_types: [],
          active_agents: [],
        },
      }),
    sendCommunicationMessage: jest.fn().mockResolvedValue({ data: null }),
  },
}));

jest.mock('../ui/ToastContainer', () => ({
  useToastActions: () => ({
    success: jest.fn(),
    error: jest.fn(),
  }),
}));

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  public onmessage: ((event: MessageEvent) => void) | null = null;
  public onclose: ((event: CloseEvent) => void) | null = null;
  public readyState = MockWebSocket.CONNECTING;
  public url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(): void {
    // noop
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

describe('CommunicationHub realtime toggle', () => {
  const OriginalWebSocket = global.WebSocket;

  beforeEach(() => {
    jest.useFakeTimers();
    MockWebSocket.instances = [];
    // @ts-expect-error - assigning mock WebSocket for test environment
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
    global.WebSocket = OriginalWebSocket;
  });

  it('avoids scheduling reconnection after realtime is disabled', async () => {
    const setTimeoutSpy = jest.spyOn(global, 'setTimeout');

    render(
      <CommunicationHub
        organizationId={42}
        tenantId={42}
        userId={7}
        currentUser={{ id: 7, email: 'test@example.com', name: 'Test User' }}
      />,
    );

    const socket = MockWebSocket.instances[0];
    expect(socket).toBeDefined();
    const originalOnClose = socket.onclose;
    expect(originalOnClose).toBeDefined();

    const eventsTab = await screen.findByRole('button', { name: /^Events/i });
    fireEvent.click(eventsTab);

    const toggleButton = await screen.findByRole('button', { name: /Live updates on/i });
    fireEvent.click(toggleButton);
    await screen.findByRole('button', { name: /Enable live updates/i });

    const timeoutCallsBefore = setTimeoutSpy.mock.calls.length;
    if (originalOnClose) {
      act(() => {
        originalOnClose({
          code: 1000,
          reason: 'remote-close',
        } as CloseEvent);
      });
    }

    const socketsBeforeTimers = MockWebSocket.instances.length;

    act(() => {
      jest.advanceTimersByTime(6000);
    });

    const newTimeoutCalls = setTimeoutSpy.mock.calls.slice(timeoutCallsBefore);
    const scheduledReconnect = newTimeoutCalls.some((call) => call[1] === 5000);
    expect(scheduledReconnect).toBe(false);
    expect(MockWebSocket.instances).toHaveLength(socketsBeforeTimers);
    setTimeoutSpy.mockRestore();
  });
});
