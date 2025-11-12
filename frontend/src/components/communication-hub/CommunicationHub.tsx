import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Loader2 } from 'lucide-react';
import { useToastActions } from '../ui/ToastContainer';
import { apiService } from '../../services/api';
import webSocketService from '../../services/websocket';
import { normalizeWebSocketBaseUrl } from '../../lib/websocketUrl';
import type {
  Agent,
  AgentEvent,
  AgentEventFilters,
  AgentEventsSummary,
  ApprovalRequest,
  CommunicationHubFilters,
  Conversation,
} from '../../types';
import { stringifyId } from '../../lib/utils';
import HeaderSection from './HeaderSection';
import TabNavigation from './TabNavigation';
import ConversationsSection from './ConversationsSection';
import ApprovalsSection from './ApprovalsSection';
import AgentsSection from './AgentsSection';
import EventsSection from './EventsSection';
import { CreateConversationDialog } from './CreateConversationDialog';
import type {
  CommunicationHubProps,
  CommunicationHubTab,
  CreateConversationPayload,
} from './types';

const buildAgentEventsWebSocketUrl = ({
  organizationId,
  tenantId,
  userId,
}: {
  organizationId: string;
  tenantId: string;
  userId: string;
}): string => {
  const base =
    process.env.NEXT_PUBLIC_AGENT_EVENTS_WEBSOCKET_URL ??
    process.env.NEXT_PUBLIC_WEBSOCKET_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8888');

  const preferSecure = typeof window !== 'undefined'
    ? window.location?.protocol === 'https:'
    : process.env.NODE_ENV === 'production';

  let fallbackHost: string | undefined;
  const locationHost = typeof window !== 'undefined' ? window.location?.host : undefined;
  if (locationHost) {
    const scheme = preferSecure ? 'https' : 'http';
    fallbackHost = `${scheme}://${locationHost}`;
  }

  const url = normalizeWebSocketBaseUrl(base, {
    preferSecure,
    ...(fallbackHost && { fallbackHost }),
  });

  let path = process.env.NEXT_PUBLIC_AGENT_EVENTS_PATH ?? '/api/agent-events/ws';
  if (!path.startsWith('/')) {
    path = `/${path}`;
  }
  path = path.replace(/\/{2,}/g, '/');
  url.pathname = path;

  url.searchParams.set('organization_id', organizationId);
  url.searchParams.set('tenant_id', tenantId);
  url.searchParams.set('user_id', userId);

  return url.toString();
};

const CommunicationHub: React.FC<CommunicationHubProps> = ({
  organizationId,
  tenantId,
  userId,
  currentUser,
}) => {
  const { success, error } = useToastActions();
  const [activeTab, setActiveTab] = useState<CommunicationHubTab>('conversations');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [filters, setFilters] = useState<CommunicationHubFilters>({});
  const [agents, setAgents] = useState<Agent[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [eventsSummary, setEventsSummary] = useState<AgentEventsSummary | null>(null);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventFilters, setEventFilters] = useState<AgentEventFilters>({ limit: 50 });
  const [realtimeEnabled, setRealtimeEnabled] = useState(true);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isSavingConversation, setIsSavingConversation] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const realtimeEnabledRef = useRef(realtimeEnabled);

  const organizationKey = useMemo(
    () => stringifyId(organizationId),
    [organizationId],
  );
  const tenantKey = useMemo(
    () => stringifyId(tenantId ?? organizationId),
    [tenantId, organizationId],
  );
  const userKey = useMemo(
    () => stringifyId(userId ?? currentUser?.id ?? undefined),
    [userId, currentUser?.id],
  );

  const loadCommunicationData = useCallback(async () => {
    if (!organizationKey) {
      setConversations([]);
      setAgents([]);
      setPendingApprovals([]);
      setConversationsLoading(false);
      return;
    }

    try {
      setConversationsLoading(true);

      const [conversationsRes, agentsRes, approvalsRes] = await Promise.all([
        apiService.getCommunicationConversations({
          ...filters,
          organization_id: organizationKey,
        }),
        apiService.getCommunicationAgents({ organization_id: organizationKey }),
        apiService.getApprovalRequests({
          tenantId: tenantKey ?? organizationKey ?? '',
          status: 'pending',
          page: 1,
          limit: 20,
        }),
      ]);

      setConversations(conversationsRes.data ?? []);
      setAgents(agentsRes.data ?? []);
      setPendingApprovals(approvalsRes.data ?? []);
    } catch (err) {
      console.error('Failed to load communication hub data:', err);
      error('Failed to load communication data');
    } finally {
      setConversationsLoading(false);
    }
  }, [organizationKey, tenantKey, filters, error]);

  const loadAgentEventsData = useCallback(async () => {
    if (!organizationKey) {
      setAgentEvents([]);
      setEventsSummary(null);
      setEventsLoading(false);
      return;
    }

    try {
      setEventsLoading(true);
      const requestFilters: AgentEventFilters = {
        ...eventFilters,
        organization_id: organizationKey,
        limit: eventFilters.limit ?? 50,
      };

      const [eventsRes, summaryRes] = await Promise.all([
        apiService.getAgentEvents(requestFilters),
        apiService.getAgentEventsSummary(organizationKey),
      ]);

      setAgentEvents(eventsRes.data ?? []);
      setEventsSummary(summaryRes.data ?? null);
    } catch (err) {
      console.error('Failed to load agent events:', err);
    } finally {
      setEventsLoading(false);
    }
  }, [eventFilters, organizationKey]);

  useEffect(() => {
    loadCommunicationData();
  }, [loadCommunicationData]);

  useEffect(() => {
    loadAgentEventsData();
  }, [loadAgentEventsData]);

  const handleNewMessage = useCallback(
    async (conversationId: string, content: string, messageType: 'text' | 'approval_request' = 'text') => {
      if (!organizationKey) {
        return;
      }

      try {
        const response = await apiService.sendCommunicationMessage({
          conversation_id: conversationId,
          content,
          message_type: messageType,
          organization_id: organizationKey,
        });

        const newMessage = response.data;
        if (newMessage) {
          setConversations((prev) =>
            prev.map((conversation) =>
              conversation.id === conversationId
                ? {
                    ...conversation,
                    messages: [...(conversation.messages ?? []), newMessage],
                  }
                : conversation,
            ),
          );
          success('Message sent successfully');
        }
      } catch (err) {
        console.error('Failed to send message:', err);
        error('Failed to send message');
      }
    },
    [organizationKey, error, success],
  );

  const handleApprovalDecision = useCallback(
    async (approvalId: string, decision: 'approved' | 'rejected', notes?: string) => {
      try {
        await apiService.makeApprovalDecision(
          approvalId,
          {
            decision: decision === 'approved' ? 'approve' : 'reject',
            notes: notes ?? '',
          },
          userKey ?? 'dashboard',
        );
        setPendingApprovals((prev) =>
          prev.filter((approval) => approval.approval_id !== approvalId),
        );
        success(`Approval ${decision} successfully`);
        loadCommunicationData();
      } catch (err) {
        console.error('Failed to process approval decision:', err);
        error('Failed to process approval');
      }
    },
    [userKey, success, error, loadCommunicationData],
  );

  const handleCreateConversation = useCallback(
    async (payload: CreateConversationPayload) => {
      if (!organizationKey) {
        return;
      }
      try {
        setIsSavingConversation(true);
        const response = await apiService.createCommunicationConversation({
          ...payload,
          organization_id: organizationKey,
        });

      const createdConversation = response.data;
      if (createdConversation) {
        setConversations((prev) => [createdConversation, ...prev]);
        success('Conversation created successfully');
        setIsCreateModalOpen(false);
      }
      } catch (err) {
        console.error('Failed to create conversation:', err);
        error('Failed to create conversation');
        throw err;
      } finally {
        setIsSavingConversation(false);
      }
    },
    [organizationKey, success, error],
  );

  const handleEventAction = useCallback(
    async (action: string, event: AgentEvent) => {
      switch (action) {
        case 'mark_completed':
          success('Event marked as completed');
          await loadAgentEventsData();
          break;
        case 'open_linkedin': {
          const linkedinUrl = event.metadata?.linkedinUrl;
          if (typeof linkedinUrl === 'string' && linkedinUrl.trim().length > 0) {
            window.open(linkedinUrl, '_blank', 'noopener');
          }
          break;
        }
        default:
          success(`Action "${action}" applied`);
      }
    },
    [loadAgentEventsData, success],
  );

  const handleSuggestionClick = useCallback(
    async (suggestion: string, event: AgentEvent) => {
      try {
        const normalizedSuggestion = suggestion.toLowerCase();
        if (normalizedSuggestion.includes('approve') && normalizedSuggestion.includes('email')) {
          const approvalIdRaw = event.metadata?.approval_id ?? event.metadata?.approvalId;
          const approvalId = typeof approvalIdRaw === 'string' ? approvalIdRaw : undefined;
          if (approvalId) {
            await apiService.makeApprovalDecision(
              approvalId,
              {
                decision: 'approve',
                notes: 'Auto-approved via suggestion',
              },
              userKey ?? 'dashboard',
            );
            success('Email approved and sent successfully');
            const approvalsRes = await apiService.getApprovalRequests({
              tenantId: tenantKey ?? organizationKey ?? '',
              status: 'pending',
              page: 1,
              limit: 10,
            });
            setPendingApprovals(approvalsRes.data ?? []);
          } else {
            error('No approval ID found for this suggestion');
          }
          return;
        }

        if (normalizedSuggestion.includes('retry')) {
          const workflowIdRaw = event.metadata?.workflow_id ?? event.metadata?.workflowId;
          const workflowId = typeof workflowIdRaw === 'string' ? workflowIdRaw : undefined;
          const effectiveTenant = tenantKey ?? organizationKey;
          if (workflowId && typeof effectiveTenant === 'string' && effectiveTenant) {
            await apiService.retryCorporateWorkflow(effectiveTenant, workflowId);
            success('Workflow retried successfully');
            await loadAgentEventsData();
          } else {
            error('Missing workflow context for retry');
          }
          return;
        }

        await handleEventAction(
          normalizedSuggestion.replace(/\s+/g, '_'),
          event,
        );
      } catch (err) {
        console.error('Failed to apply suggestion:', err);
        error('Failed to apply suggestion');
      }
    },
    [
      error,
      handleEventAction,
      loadAgentEventsData,
      organizationKey,
      success,
      tenantKey,
      userKey,
    ],
  );

  useEffect(() => {
    realtimeEnabledRef.current = realtimeEnabled;
    if (!realtimeEnabled) {
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (wsRef.current) {
        const socket = wsRef.current;
        socket.onclose = null;
        socket.close();
        wsRef.current = null;
      }
    }
  }, [realtimeEnabled]);

  useEffect(() => {
    if (!organizationKey || !realtimeEnabled) {
      return () => {
        if (reconnectTimeoutRef.current !== null) {
          clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }
        if (wsRef.current) {
          const socket = wsRef.current;
          socket.onclose = null;
          socket.close();
          wsRef.current = null;
        }
      };
    }

    let cancelled = false;

    function clearReconnectTimer() {
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    }

    function scheduleReconnect() {
      if (!realtimeEnabledRef.current || cancelled) {
        return;
      }
      clearReconnectTimer();
      reconnectTimeoutRef.current = window.setTimeout(() => {
        reconnectTimeoutRef.current = null;
        setupWebSocket();
      }, 5000);
    }

    function setupWebSocket() {
      if (cancelled || !realtimeEnabledRef.current) {
        return;
      }
      if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) {
        return;
      }

      const tenantContext = tenantKey ?? organizationKey;
      const userContext = userKey ?? currentUser?.id ?? 'dashboard';
      const wsUrl = buildAgentEventsWebSocketUrl({
        organizationId: String(organizationKey),
        tenantId: String(tenantContext),
        userId: String(userContext),
      });

      try {
        const socket = new WebSocket(wsUrl);
        wsRef.current = socket;

        socket.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data) as { type: string; data?: AgentEvent };
            if (payload.type === 'agent_event' && payload.data) {
              const eventData = payload.data as AgentEvent;
              setAgentEvents((prev) => [eventData, ...prev.slice(0, 99)]);
              if (eventData.level === 'error' || eventData.level === 'critical') {
                error(`Agent ${eventData.agent_id}: ${eventData.message}`);
              } else if (eventData.suggestion) {
                success(`Suggestion from ${eventData.agent_id}: ${eventData.suggestion}`);
              }
            }
          } catch (err) {
            console.error('Failed to parse agent event message', err);
          }
        };

        socket.onclose = () => {
          wsRef.current = null;
          if (!cancelled) {
            scheduleReconnect();
          }
        };
      } catch (err) {
        console.error('Failed to establish agent events WebSocket', err);
        scheduleReconnect();
      }
    }

    setupWebSocket();

    return () => {
      cancelled = true;
      clearReconnectTimer();
      if (wsRef.current) {
        const socket = wsRef.current;
        wsRef.current = null;
        socket.onclose = null;
        socket.close();
      }
    };
  }, [
    organizationKey,
    tenantKey,
    userKey,
    realtimeEnabled,
    currentUser?.id,
    error,
    success,
  ]);

  useEffect(() => {
    webSocketService.on('communication_update', loadCommunicationData);
    return () => {
      webSocketService.off('communication_update', loadCommunicationData);
    };
  }, [loadCommunicationData]);

  if (!organizationKey) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Waiting for organization context…
      </div>
    );
  }

  return (
    <div className="h-full space-y-6">
      <HeaderSection activeTab={activeTab} />

      <TabNavigation
        activeTab={activeTab}
        onChange={setActiveTab}
        pendingApprovals={pendingApprovals.length}
        activeAgents={agents.filter((agent) => agent.status === 'active').length}
        eventsSummary={eventsSummary}
        realtimeEnabled={realtimeEnabled}
      />

      <div className="flex-1 min-h-0">
        {activeTab === 'conversations' && (
          <ConversationsSection
            conversations={conversations}
            filters={filters}
            setFilters={setFilters}
            loading={conversationsLoading}
            onCreateConversation={() => setIsCreateModalOpen(true)}
            onSendMessage={handleNewMessage}
          />
        )}

        {activeTab === 'approvals' && (
          <ApprovalsSection approvals={pendingApprovals} onDecision={handleApprovalDecision} />
        )}

        {activeTab === 'agents' && (
          <AgentsSection
            agents={agents}
            onAgentAction={(agentId, action) =>
              success(`Action "${action}" queued for agent ${agentId}`)
            }
          />
        )}

        {activeTab === 'events' && (
          <EventsSection
            events={agentEvents}
            summary={eventsSummary}
            loading={eventsLoading}
            filters={eventFilters}
            onFiltersChange={setEventFilters}
            realTimeEnabled={realtimeEnabled}
            onToggleRealtime={() => setRealtimeEnabled((prev) => !prev)}
            onSuggestionClick={handleSuggestionClick}
          />
        )}
      </div>

      <CreateConversationDialog
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onSubmit={handleCreateConversation}
        isSubmitting={isSavingConversation}
      />
    </div>
  );
};

export default CommunicationHub;
