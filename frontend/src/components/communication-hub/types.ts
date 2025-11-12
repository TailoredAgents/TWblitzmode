import type { Dispatch, SetStateAction } from 'react';
import type {
  Agent,
  AgentEvent,
  AgentEventFilters,
  AgentEventsSummary,
  ApprovalRequest,
  CommunicationHubFilters,
  Conversation,
} from '../../types';

export type ConversationPriority = 'low' | 'medium' | 'high';
export type ConversationChannel = 'email' | 'phone' | 'meeting' | 'linkedin';
export type CommunicationHubTab = 'conversations' | 'approvals' | 'agents' | 'events';

export interface CreateConversationParticipant {
  id: string;
  name: string;
  type: 'human' | 'ai';
}

export interface CreateConversationPayload {
  title: string;
  participants: CreateConversationParticipant[];
  status: 'active';
  priority: ConversationPriority;
  metadata?: {
    channel: ConversationChannel;
    notes?: string;
    scheduled_for?: string;
  };
}

export interface CommunicationHubProps {
  organizationId: string | number;
  tenantId?: string | number;
  userId?: string | number;
  currentUser?: {
    id: string | number;
    tenant_id?: string | number;
    organization_id?: string | number;
    email?: string;
    name?: string;
  };
}

export interface ConversationsSectionState {
  searchQuery: string;
}

export interface ConversationsSectionProps {
  conversations: Conversation[];
  filters: CommunicationHubFilters;
  setFilters: Dispatch<SetStateAction<CommunicationHubFilters>>;
  loading: boolean;
  onCreateConversation: () => void;
  onSendMessage: (
    conversationId: string,
    content: string,
    messageType?: 'text' | 'approval_request'
  ) => void;
}

export interface ApprovalsSectionProps {
  approvals: ApprovalRequest[];
  onDecision: (approvalId: string, decision: 'approved' | 'rejected', notes?: string) => void;
}

export interface AgentsSectionProps {
  agents: Agent[];
  onAgentAction?: (agentId: string, action: string) => void;
}

export interface EventsSectionProps {
  events: AgentEvent[];
  summary: AgentEventsSummary | null;
  loading: boolean;
  filters: AgentEventFilters;
  onFiltersChange: Dispatch<SetStateAction<AgentEventFilters>>;
  realTimeEnabled: boolean;
  onToggleRealtime: () => void;
  onSuggestionClick: (suggestion: string, event: AgentEvent) => Promise<void> | void;
}
