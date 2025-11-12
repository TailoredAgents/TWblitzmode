import React, { useMemo } from 'react';
import type { CommunicationHubTab } from './types';

interface HeaderSectionProps {
  activeTab: CommunicationHubTab;
}

const TAB_DESCRIPTIONS: Record<CommunicationHubTab, string> = {
  conversations: 'Monitor threads across Link agents and human operators.',
  approvals: 'Review pending agent escalations before they reach prospects.',
  agents: 'Track Link agent health, activity, and current assignments.',
  events: 'Inspect real-time telemetry from Link automations.',
};

const HeaderSection: React.FC<HeaderSectionProps> = ({ activeTab }) => {
  const description = useMemo(() => {
    switch (activeTab) {
      case 'approvals':
        return TAB_DESCRIPTIONS.approvals;
      case 'agents':
        return TAB_DESCRIPTIONS.agents;
      case 'events':
        return TAB_DESCRIPTIONS.events;
      case 'conversations':
      default:
        return TAB_DESCRIPTIONS.conversations;
    }
  }, [activeTab]);

  return (
    <header className="flex flex-col gap-1">
      <h1 className="text-2xl font-bold text-foreground">Communication Hub</h1>
      <p className="text-muted-foreground">{description}</p>
    </header>
  );
};

export default HeaderSection;
