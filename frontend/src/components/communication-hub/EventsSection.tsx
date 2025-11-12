import React, { useState } from 'react';
import { X } from 'lucide-react';
import GlassCard from '../ui/GlassCard';
import AgentEventsFeed from '../ui/AgentEventsFeed';
import type { AgentEvent } from '../../types';
import type { EventsSectionProps } from './types';

const EventsSection: React.FC<EventsSectionProps> = ({
  events,
  summary,
  loading,
  filters,
  onFiltersChange,
  realTimeEnabled,
  onToggleRealtime,
  onSuggestionClick,
}) => {
  const [selectedEvent, setSelectedEvent] = useState<AgentEvent | null>(null);

  return (
    <section className="space-y-4">
      {summary && (
        <GlassCard className="flex flex-wrap items-center gap-4 p-4 text-sm text-muted-foreground">
          <span>
            <strong className="text-foreground">{summary.level_counts.error ?? 0}</strong> errors last 50 events
          </span>
          <span>
            <strong className="text-foreground">{summary.level_counts.warning ?? 0}</strong> warnings
          </span>
          <span>
            <strong className="text-foreground">{summary.active_agents.length}</strong> active agents reporting
          </span>
          <button
            type="button"
            onClick={onToggleRealtime}
            className={`ml-auto inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors ${
              realTimeEnabled
                ? 'border-green-500/50 bg-green-500/10 text-green-500'
                : 'border-border/40 bg-background/70 text-muted-foreground hover:text-foreground'
            }`}
          >
            {realTimeEnabled ? 'Live updates on' : 'Enable live updates'}
          </button>
        </GlassCard>
      )}

      <AgentEventsFeed
        events={events}
        loading={loading}
        onEventSelect={(event) => setSelectedEvent(event)}
        onSuggestionClick={onSuggestionClick}
        filters={filters}
        onFiltersChange={onFiltersChange}
        realTimeEnabled={realTimeEnabled}
      />

      {selectedEvent && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm">
          <div className="relative w-full max-w-2xl">
            <GlassCard className="space-y-4 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-foreground">Agent event</h2>
                  <p className="text-xs text-muted-foreground">
                    {new Date(selectedEvent.created_at).toLocaleString()} · {selectedEvent.agent_id}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedEvent(null)}
                  className="rounded-full border border-border/40 p-1 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                  <span className="sr-only">Close</span>
                </button>
              </div>

              <div className="space-y-3 text-sm text-foreground">
                <p className="font-medium">{selectedEvent.message}</p>
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span className="rounded-full bg-muted/30 px-2 py-1">Type: {selectedEvent.event_type}</span>
                  <span className="rounded-full bg-muted/30 px-2 py-1">Level: {selectedEvent.level}</span>
                  {selectedEvent.workflow_id && (
                    <span className="rounded-full bg-muted/30 px-2 py-1">
                      Workflow: {selectedEvent.workflow_id}
                    </span>
                  )}
                </div>
                {selectedEvent.suggestion && (
                  <GlassCard className="border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-foreground">
                    <p className="font-semibold text-amber-600 dark:text-amber-300">Suggestion</p>
                    <p className="mt-1 text-amber-700 dark:text-amber-200">{selectedEvent.suggestion}</p>
                  </GlassCard>
                )}
                {selectedEvent.metadata && Object.keys(selectedEvent.metadata).length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                      Metadata
                    </p>
                    <pre className="max-h-64 overflow-auto rounded-lg bg-background/90 p-3 text-xs text-muted-foreground">
                      {JSON.stringify(selectedEvent.metadata, null, 2)}
                    </pre>
                  </div>
                )}
              </div>

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setSelectedEvent(null)}
                  className="rounded-lg border border-border/30 px-4 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                  Close
                </button>
              </div>
            </GlassCard>
          </div>
        </div>
      )}
    </section>
  );
};

export default EventsSection;
