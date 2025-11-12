import React from 'react';
import AgentStatusPanel from '../ui/AgentStatusPanel';
import type { AgentsSectionProps } from './types';

const AgentsSection: React.FC<AgentsSectionProps> = ({ agents, onAgentAction }) => {
  const handleAgentAction =
    onAgentAction ??
    ((agentId: string, action: 'start' | 'pause' | 'stop' | 'configure') => {
      void agentId;
      void action;
    });
  return (
    <section className="space-y-4">
      <AgentStatusPanel agents={agents} onAgentAction={handleAgentAction} />
    </section>
  );
};

export default AgentsSection;
