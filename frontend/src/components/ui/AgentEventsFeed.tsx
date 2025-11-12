// Agent Events Feed - Real-time Agent Events Display
// September 2025 AI Integration with Actionable Suggestions

'use client';

import React, { useState } from 'react';
import {
  AlertCircle,
  CheckCircle,
  Info,
  AlertTriangle,
  Zap,
  Filter,
  RefreshCw,
  Clock,
  User,
  Lightbulb
} from 'lucide-react';
import GlassCard from './GlassCard';
import type {
  AgentEventsFeedProps,
  AgentEvent,
  AgentEventLevel,
  AgentEventFilters,
  AgentEventType,
} from '../../types';

const AGENT_EVENT_LEVELS: readonly AgentEventLevel[] = ['debug', 'info', 'warning', 'error', 'critical'];
const AGENT_EVENT_TYPES: readonly AgentEventType[] = [
  'agent_start',
  'agent_stop',
  'agent_error',
  'task_start',
  'task_complete',
  'task_error',
  'api_call',
  'api_response',
  'workflow_start',
  'workflow_complete',
  'user_interaction',
  'approval_request',
  'approval_decision',
  'communication',
  'system_event',
];

const isAgentEventLevel = (value: string): value is AgentEventLevel =>
  AGENT_EVENT_LEVELS.includes(value as AgentEventLevel);

const isAgentEventType = (value: string): value is AgentEventType =>
  AGENT_EVENT_TYPES.includes(value as AgentEventType);

const AgentEventsFeed: React.FC<AgentEventsFeedProps> = ({
  events,
  loading = false,
  onEventSelect,
  onSuggestionClick,
  filters,
  onFiltersChange,
  realTimeEnabled = false,
  className = ''
}) => {
  const [showFilters, setShowFilters] = useState(false);

  const getLevelIcon = (level: AgentEventLevel) => {
    switch (level) {
      case 'critical':
        return <AlertCircle className="w-4 h-4 text-red-500" />;
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-400" />;
      case 'warning':
        return <AlertTriangle className="w-4 h-4 text-yellow-500" />;
      case 'info':
        return <Info className="w-4 h-4 text-blue-500" />;
      case 'debug':
        return <CheckCircle className="w-4 h-4 text-gray-500" />;
      default:
        return <Info className="w-4 h-4 text-blue-500" />;
    }
  };

  const getLevelColor = (level: AgentEventLevel) => {
    switch (level) {
      case 'critical':
        return 'border-red-500/50 bg-red-500/5';
      case 'error':
        return 'border-red-400/50 bg-red-400/5';
      case 'warning':
        return 'border-yellow-500/50 bg-yellow-500/5';
      case 'info':
        return 'border-blue-500/50 bg-blue-500/5';
      case 'debug':
        return 'border-gray-500/50 bg-gray-500/5';
      default:
        return 'border-blue-500/50 bg-blue-500/5';
    }
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMinutes = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMinutes / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMinutes < 1) return 'Just now';
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const handleFilterChange = (
    key: 'level' | 'event_type' | 'agent_id',
    value: string | undefined,
  ) => {
    if (!onFiltersChange) {
      return;
    }

    const nextFilters: AgentEventFilters = { ...(filters ?? {}) };

    const normalizedValue = value && value.trim().length > 0 ? value : undefined;

    if (normalizedValue === undefined) {
      if (key === 'level') delete nextFilters.level;
      if (key === 'event_type') delete nextFilters.event_type;
      if (key === 'agent_id') delete nextFilters.agent_id;
    } else if (key === 'level') {
      if (isAgentEventLevel(normalizedValue)) {
        nextFilters.level = normalizedValue;
      }
    } else if (key === 'event_type') {
      if (isAgentEventType(normalizedValue)) {
        nextFilters.event_type = normalizedValue;
      }
    } else if (key === 'agent_id') {
      nextFilters.agent_id = normalizedValue;
    }

    onFiltersChange(nextFilters);
  };

  const SuggestionCallout: React.FC<{ event: AgentEvent }> = ({ event }) => {
    const suggestion = event.suggestion;
    if (!suggestion) return null;

    return (
      <div className="mt-3 p-3 bg-gradient-to-r from-amber-500/10 to-orange-500/10 border border-amber-500/20 rounded-lg">
        <div className="flex items-start gap-2">
          <Lightbulb className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <p className="text-sm text-foreground font-medium mb-1">Suggestion:</p>
            <p className="text-sm text-muted-foreground">{event.suggestion}</p>
            {onSuggestionClick && (
              <button
                onClick={() => onSuggestionClick(suggestion, event)}
                className="mt-2 text-xs px-2 py-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-700 dark:text-amber-300 rounded transition-colors"
              >
                Apply Suggestion
              </button>
            )}
          </div>
        </div>
      </div>
    );
  };

  const EventCard: React.FC<{ event: AgentEvent }> = ({ event }) => (
    <GlassCard
      className={`p-4 transition-all hover:shadow-lg cursor-pointer border-l-4 ${getLevelColor(event.level)} ${className}`}
      onClick={() => onEventSelect?.(event)}
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0">
          {getLevelIcon(event.level)}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">
                {event.agent_id}
              </span>
              <span className="text-xs px-2 py-1 bg-muted/50 rounded-full text-muted-foreground">
                {event.event_type.replace('_', ' ')}
              </span>
            </div>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Clock className="w-3 h-3" />
              {formatTimestamp(event.created_at)}
            </div>
          </div>

          <p className="text-sm text-foreground mb-2">{event.message}</p>

          {event.metadata && Object.keys(event.metadata).length > 0 && (
            <div className="mt-2 p-2 bg-muted/20 rounded text-xs">
              <details className="cursor-pointer">
                <summary className="text-muted-foreground hover:text-foreground">
                  View metadata
                </summary>
                <pre className="mt-1 text-xs overflow-x-auto">
                  {JSON.stringify(event.metadata, null, 2)}
                </pre>
              </details>
            </div>
          )}

          <SuggestionCallout event={event} />
        </div>
      </div>
    </GlassCard>
  );

  if (loading && events.length === 0) {
    return (
      <GlassCard className={`p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">Loading events...</span>
        </div>
      </GlassCard>
    );
  }

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold text-foreground">Agent Events</h3>
          {realTimeEnabled && (
            <div className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
              <Zap className="w-3 h-3" />
              Live
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`p-2 rounded-lg border transition-colors ${
              showFilters
                ? 'bg-primary/10 border-primary/20 text-primary'
                : 'bg-background/80 border-border/20 hover:bg-muted/20 text-muted-foreground'
            }`}
          >
            <Filter className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Filters */}
      {showFilters && (
        <GlassCard className="p-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">
                Level
              </label>
              <select
                value={filters?.level ?? ''}
                onChange={(e) => handleFilterChange('level', e.target.value || undefined)}
                className="w-full px-3 py-2 bg-background/80 border border-border/20 rounded-lg text-foreground"
              >
                <option value="">All levels</option>
                <option value="critical">Critical</option>
                <option value="error">Error</option>
                <option value="warning">Warning</option>
                <option value="info">Info</option>
                <option value="debug">Debug</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">
                Event Type
              </label>
              <select
                value={filters?.event_type ?? ''}
                onChange={(e) => handleFilterChange('event_type', e.target.value || undefined)}
                className="w-full px-3 py-2 bg-background/80 border border-border/20 rounded-lg text-foreground"
              >
                <option value="">All types</option>
                <option value="agent_start">Agent Start</option>
                <option value="agent_stop">Agent Stop</option>
                <option value="agent_error">Agent Error</option>
                <option value="task_start">Task Start</option>
                <option value="task_complete">Task Complete</option>
                <option value="task_error">Task Error</option>
                <option value="system_event">System Event</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1">
                Agent ID
              </label>
              <input
                type="text"
                value={filters?.agent_id ?? ''}
                onChange={(e) => handleFilterChange('agent_id', e.target.value || undefined)}
                placeholder="Filter by agent..."
                className="w-full px-3 py-2 bg-background/80 border border-border/20 rounded-lg text-foreground placeholder:text-muted-foreground"
              />
            </div>
          </div>
        </GlassCard>
      )}

      {/* Events List */}
      <div className="space-y-3 max-h-[calc(100vh-300px)] overflow-y-auto">
        {events.length === 0 ? (
          <GlassCard className="p-8 text-center">
            <User className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-foreground mb-2">No Events</h3>
            <p className="text-muted-foreground">
              {realTimeEnabled
                ? "Waiting for agent events..."
                : "No agent events found with the current filters."
              }
            </p>
          </GlassCard>
        ) : (
          events.map((event) => (
            <EventCard key={`${event.id}-${event.event_id}`} event={event} />
          ))
        )}
      </div>
    </div>
  );
};

export default AgentEventsFeed;
