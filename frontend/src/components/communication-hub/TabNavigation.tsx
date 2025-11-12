import React from 'react';
import { Activity, Bell, MessageSquare, Users, Zap } from 'lucide-react';
import type { AgentEventsSummary } from '../../types';
import type { CommunicationHubTab } from './types';

interface TabNavigationProps {
  activeTab: CommunicationHubTab;
  onChange: (tab: CommunicationHubTab) => void;
  pendingApprovals: number;
  activeAgents: number;
  eventsSummary: AgentEventsSummary | null;
  realtimeEnabled: boolean;
}

const TabNavigation: React.FC<TabNavigationProps> = ({
  activeTab,
  onChange,
  pendingApprovals,
  activeAgents,
  eventsSummary,
  realtimeEnabled,
}) => {
  return (
    <div className="flex items-center gap-1 rounded-lg bg-muted/20 p-1">
      <button
        onClick={() => onChange('conversations')}
        className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
          activeTab === 'conversations'
            ? 'bg-background/80 text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/10'
        }`}
      >
        <MessageSquare className="h-4 w-4" />
        Conversations
      </button>

      <button
        onClick={() => onChange('approvals')}
        className={`relative flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
          activeTab === 'approvals'
            ? 'bg-background/80 text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/10'
        }`}
      >
        <Bell className="h-4 w-4" />
        Approvals
        {pendingApprovals > 0 && (
          <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-xs text-white">
            {pendingApprovals}
          </span>
        )}
      </button>

      <button
        onClick={() => onChange('agents')}
        className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
          activeTab === 'agents'
            ? 'bg-background/80 text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/10'
        }`}
      >
        <Users className="h-4 w-4" />
        Agents ({activeAgents})
      </button>

      <button
        onClick={() => onChange('events')}
        className={`relative flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
          activeTab === 'events'
            ? 'bg-background/80 text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/10'
        }`}
      >
        <Activity className="h-4 w-4" />
        Events
        {realtimeEnabled && <Zap className="h-3 w-3 text-green-500 animate-pulse" />}
        {eventsSummary && eventsSummary.level_counts.error > 0 && (
          <span className="absolute -top-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-xs text-white">
            {eventsSummary.level_counts.error}
          </span>
        )}
      </button>
    </div>
  );
};

export default TabNavigation;
