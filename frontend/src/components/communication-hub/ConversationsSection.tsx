import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, MessageSquare, Plus, Search } from 'lucide-react';
import ConversationsList from '../ui/ConversationsList';
import MessageThread from '../ui/MessageThread';
import GlassCard from '../ui/GlassCard';
import type { CommunicationHubFilters, Conversation } from '../../types';
import type { ConversationsSectionProps } from './types';
import { cn } from '../../lib/utils';

const STATUS_OPTIONS: Array<CommunicationHubFilters['status'] | ''> = [
  '',
  'active',
  'paused',
  'pending_approval',
  'archived',
];

const PRIORITY_OPTIONS: Array<CommunicationHubFilters['priority'] | ''> = ['', 'low', 'medium', 'high'];

const PARTICIPANT_OPTIONS: Array<CommunicationHubFilters['participant_type'] | ''> = ['', 'human', 'ai'];

const ConversationsSection: React.FC<ConversationsSectionProps> = ({
  conversations,
  filters,
  setFilters,
  loading,
  onCreateConversation,
  onSendMessage,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);

  const filteredConversations = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();

    return conversations.filter((conversation) => {
      if (filters.status && conversation.status !== filters.status) {
        return false;
      }

      if (filters.priority && conversation.priority !== filters.priority) {
        return false;
      }

      if (filters.participant_type) {
        const hasParticipant = conversation.participants.some(
          (participant) => participant.type === filters.participant_type
        );
        if (!hasParticipant) {
          return false;
        }
      }

      if (!query) {
        return true;
      }

      const titleMatch = conversation.title?.toLowerCase().includes(query);
      const participantMatch = conversation.participants.some((participant) =>
        participant.name?.toLowerCase().includes(query)
      );
      const lastMessage = conversation.messages?.at(-1)?.content?.toLowerCase() ?? '';

      return titleMatch || participantMatch || lastMessage.includes(query);
    });
  }, [conversations, filters.priority, filters.participant_type, filters.status, searchQuery]);

  useEffect(() => {
    if (!filteredConversations.length) {
      setSelectedConversationId(null);
      return;
    }

    const firstConversation = filteredConversations[0];

    if (!selectedConversationId) {
      setSelectedConversationId(firstConversation?.id ?? null);
      return;
    }

    const exists = filteredConversations.some((conversation) => conversation.id === selectedConversationId);
    if (!exists) {
      setSelectedConversationId(firstConversation?.id ?? null);
    }
  }, [filteredConversations, selectedConversationId]);

  const selectedConversation: Conversation | null = useMemo(() => {
    if (!selectedConversationId) {
      return null;
    }
    return conversations.find((conversation) => conversation.id === selectedConversationId) ?? null;
  }, [conversations, selectedConversationId]);

  const resetFilters = () => {
    setFilters({});
    setSearchQuery('');
  };

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search conversations, participants, or recent messages..."
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            className="w-full rounded-lg border border-border/30 bg-background/80 px-10 py-2 text-sm text-foreground shadow-sm backdrop-blur focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40"
          />
        </div>
        <button
          type="button"
          onClick={onCreateConversation}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" />
          New Conversation
        </button>
      </div>

      <GlassCard className="p-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Status</span>
            <select
              value={filters.status ?? ''}
              onChange={(event) => {
                const value = event.target.value as CommunicationHubFilters['status'] | '';
                setFilters((prev) => {
                  if (!value) {
                    const { status, ...rest } = prev;
                    return rest as CommunicationHubFilters;
                  }
                  return { ...prev, status: value };
                });
              }}
              className="rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
            >
              {STATUS_OPTIONS.map((option) => {
                const optionKey = option === '' ? 'all-status' : option;
                return (
                  <option key={optionKey} value={option}>
                    {option ? option.replace('_', ' ') : 'All statuses'}
                  </option>
                );
              })}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Priority</span>
            <select
              value={filters.priority ?? ''}
              onChange={(event) => {
                const value = event.target.value as CommunicationHubFilters['priority'] | '';
                setFilters((prev) => {
                  if (!value) {
                    const { priority, ...rest } = prev;
                    return rest as CommunicationHubFilters;
                  }
                  return { ...prev, priority: value };
                });
              }}
              className="rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
            >
              {PRIORITY_OPTIONS.map((option) => {
                const optionKey = option === '' ? 'all-priority' : option;
                return (
                  <option key={optionKey} value={option}>
                    {option ? option.charAt(0).toUpperCase() + option.slice(1) : 'All priorities'}
                  </option>
                );
              })}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Participants</span>
            <select
              value={filters.participant_type ?? ''}
              onChange={(event) => {
                const value = event.target.value as CommunicationHubFilters['participant_type'] | '';
                setFilters((prev) => {
                  if (!value) {
                    const { participant_type, ...rest } = prev;
                    return rest as CommunicationHubFilters;
                  }
                  return { ...prev, participant_type: value };
                });
              }}
              className="rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
            >
              {PARTICIPANT_OPTIONS.map((option) => {
                const optionKey = option === '' ? 'all-participants' : option;
                return (
                  <option key={optionKey} value={option}>
                    {option
                      ? option === 'ai'
                        ? 'AI agent'
                        : 'Human'
                      : 'All participants'}
                  </option>
                );
              })}
            </select>
          </label>

          <button
            type="button"
            onClick={resetFilters}
            className="self-end rounded-lg border border-border/30 px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground hover:border-border/50"
          >
            Reset filters
          </button>
        </div>
      </GlassCard>

      <div className="grid min-h-[480px] gap-6 lg:grid-cols-[320px,1fr]">
        <div className="space-y-4">
          {loading ? (
            <GlassCard className="flex h-full items-center justify-center">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              <span className="text-sm text-muted-foreground">Loading conversations…</span>
            </GlassCard>
          ) : (
            <ConversationsList
              conversations={filteredConversations}
              selectedConversation={
                selectedConversationId
                  ? filteredConversations.find((conversation) => conversation.id === selectedConversationId) ?? null
                  : null
              }
              onConversationSelect={(conversation) => setSelectedConversationId(conversation?.id ?? null)}
              onNewConversation={onCreateConversation}
            />
          )}
        </div>

        <div className="space-y-4">
          {loading ? (
            <GlassCard className="flex h-full items-center justify-center">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              <span className="text-sm text-muted-foreground">Loading conversation…</span>
            </GlassCard>
          ) : selectedConversation ? (
            <MessageThread
              conversation={selectedConversation}
              onSendMessage={(content, type) =>
                onSendMessage(selectedConversation.id, content, type ?? 'text')
              }
            />
          ) : (
            <GlassCard className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <MessageSquare className="h-10 w-10 text-muted-foreground" />
              <div>
                <h3 className="text-base font-semibold text-foreground">No conversation selected</h3>
                <p className="text-sm text-muted-foreground">
                  Choose a thread on the left or start a new conversation.
                </p>
              </div>
              <button
                type="button"
                onClick={onCreateConversation}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90'
                )}
              >
                <Plus className="h-4 w-4" />
                New Conversation
              </button>
            </GlassCard>
          )}
        </div>
      </div>
    </section>
  );
};

export default ConversationsSection;
