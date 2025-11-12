// Agent Status Panel - Communication Hub Component
// September 2025 AI Integration

import React, { useState, useEffect } from 'react';
import { Bot, Activity, Pause, Play, Settings, AlertTriangle, CheckCircle, Clock } from 'lucide-react';
import GlassCard from './GlassCard';
import { cn } from '../../lib/utils';
import type { Agent } from '../../types';
import { apiService } from '../../services/api';

interface AgentStatusPanelProps {
  agents: Agent[];
  onAgentAction: (agentId: string, action: AgentActionId) => void;
}

type AgentWithTask = Agent & {
  current_task?: string;
};

type AgentActionId = 'start' | 'pause' | 'stop' | 'configure';

const AgentStatusPanel: React.FC<AgentStatusPanelProps> = ({
  agents,
  onAgentAction
}) => {
  const [selectedAgent, setSelectedAgent] = useState<AgentWithTask | null>(null);
  const [friendlyNames, setFriendlyNames] = useState<Record<string, string>>({});

  // Load friendly agent names on component mount
  useEffect(() => {
    const loadFriendlyNames = async () => {
      try {
        const response = await apiService.get<{ friendly_names?: Record<string, unknown> }>('/api/agent-events/friendly-names');
        const names = response.data?.friendly_names;
        if (names && typeof names === 'object') {
          const entries = Object.entries(names).filter(
            (entry): entry is [string, string] => typeof entry[1] === 'string'
          );
          if (entries.length > 0) {
            setFriendlyNames(Object.fromEntries(entries));
          }
        }
      } catch (error) {
        console.error('Failed to load friendly agent names:', error);
      }
    };

    loadFriendlyNames();
  }, []);

  const getStatusIcon = (status: Agent['status']) => {
    const iconClass = "w-4 h-4";

    switch (status) {
      case 'active':
        return <CheckCircle className={cn(iconClass, "text-green-500")} />;
      case 'paused':
        return <Pause className={cn(iconClass, "text-yellow-500")} />;
      case 'error':
        return <AlertTriangle className={cn(iconClass, "text-red-500")} />;
      case 'configuring':
        return <Settings className={cn(iconClass, "text-blue-500")} />;
      case 'idle':
      default:
        return <Clock className={cn(iconClass, "text-gray-500")} />;
    }
  };

  const getStatusColor = (status: Agent['status']) => {
    switch (status) {
      case 'active':
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400';
      case 'paused':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400';
      case 'error':
        return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400';
      case 'configuring':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400';
      case 'idle':
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400';
    }
  };

  const formatLastActivity = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffInMinutes = (now.getTime() - date.getTime()) / (1000 * 60);

    if (diffInMinutes < 1) {
      return 'Just now';
    } else if (diffInMinutes < 60) {
      return `${Math.floor(diffInMinutes)}m ago`;
    } else if (diffInMinutes < 1440) {
      return `${Math.floor(diffInMinutes / 60)}h ago`;
    } else {
      return `${Math.floor(diffInMinutes / 1440)}d ago`;
    }
  };

  const getAvailableActions = (agent: AgentWithTask) => {
    const actions: Array<{
      id: AgentActionId;
      label: string;
      icon: React.ComponentType<{ className?: string }>;
      variant: 'success' | 'warning' | 'danger' | 'neutral';
    }> = [];

    if (agent.status === 'paused' || agent.status === 'idle') {
      actions.push({ id: 'start', label: 'Start', icon: Play, variant: 'success' });
    }

    if (agent.status === 'active') {
      actions.push({ id: 'pause', label: 'Pause', icon: Pause, variant: 'warning' });
    }

    if (agent.status !== 'idle') {
      actions.push({ id: 'stop', label: 'Stop', icon: Pause, variant: 'danger' });
    }

    actions.push({ id: 'configure', label: 'Configure', icon: Settings, variant: 'neutral' });

    return actions;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-foreground">AI Agents</h2>
          <p className="text-sm text-muted-foreground">
            {agents.filter(a => a.status === 'active').length} of {agents.length} agents active
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Status Summary */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1">
              <div className="w-2 h-2 rounded-full bg-green-500"></div>
              <span className="text-xs text-muted-foreground">
                {agents.filter(a => a.status === 'active').length} Active
              </span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-2 h-2 rounded-full bg-yellow-500"></div>
              <span className="text-xs text-muted-foreground">
                {agents.filter(a => a.status === 'paused').length} Paused
              </span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-2 h-2 rounded-full bg-red-500"></div>
              <span className="text-xs text-muted-foreground">
                {agents.filter(a => a.status === 'error').length} Error
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Agents Grid */}
      {agents.length === 0 ? (
        <GlassCard className="text-center py-12">
          <Bot className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-foreground mb-2">No Agents Configured</h3>
          <p className="text-muted-foreground mb-6">Set up AI agents to automate your workflows</p>
          <button className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors">
            Configure Agents
          </button>
        </GlassCard>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((agentData) => {
            const agent = agentData as AgentWithTask;
            const friendlyName =
              friendlyNames[agent.id] ??
              (agent.name ? friendlyNames[agent.name] : undefined) ??
              agent.name;

            return (
              <GlassCard
                key={agent.id}
                variant="interactive"
                className={cn(
                  'p-4 cursor-pointer transition-all duration-200',
                  selectedAgent?.id === agent.id
                    ? 'ring-2 ring-primary/40 bg-primary/5'
                    : 'hover:bg-muted/10'
                )}
                onClick={() => setSelectedAgent(selectedAgent?.id === agent.id ? null : agent)}
              >
                <div className="space-y-4">
                {/* Agent Header */}
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                      <Bot className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                    </div>
                    <div>
                      <h3 className="font-medium text-foreground">
                        {friendlyName}
                      </h3>
                      <p className="text-xs text-muted-foreground">{agent.type}</p>
                    </div>
                  </div>

                  <div className="flex flex-col items-end gap-1">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(agent.status)}
                      <span className={cn(
                        'px-2 py-1 rounded text-xs font-medium',
                        getStatusColor(agent.status)
                      )}>
                        {agent.status}
                      </span>
                    </div>
                    {agent.current_task && (
                      <span className="text-xs text-muted-foreground">
                        {agent.current_task}
                      </span>
                    )}
                  </div>
                </div>

                {/* Agent Description */}
                <p className="text-sm text-muted-foreground line-clamp-2">
                  {agent.description ?? 'No description available'}
                </p>

                {/* Agent Metrics */}
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Tasks</span>
                    <p className="font-medium text-foreground">
                      {agent.metrics?.tasks_completed ?? 0}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Uptime</span>
                    <p className="font-medium text-foreground">
                      {agent.metrics?.uptime ?? '0%'}
                    </p>
                  </div>
                </div>

                {/* Last Activity */}
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Activity className="w-3 h-3" />
                  <span>Last active: {formatLastActivity(agent.last_activity)}</span>
                </div>

                {/* Agent Actions */}
                {selectedAgent?.id === agent.id && (
                  <div className="flex flex-wrap gap-2 pt-2 border-t border-border/20">
                    {getAvailableActions(agent).map((action) => {
                      const Icon = action.icon;
                      return (
                        <button
                          key={action.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            onAgentAction(agent.id, action.id);
                          }}
                          className={cn(
                            'px-3 py-1 rounded text-xs font-medium transition-colors flex items-center gap-1',
                            action.variant === 'success' && 'bg-green-100 text-green-800 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400',
                            action.variant === 'warning' && 'bg-yellow-100 text-yellow-800 hover:bg-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400',
                            action.variant === 'danger' && 'bg-red-100 text-red-800 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400',
                            action.variant === 'neutral' && 'bg-muted/30 text-muted-foreground hover:bg-muted/50'
                          )}
                        >
                          <Icon className="w-3 h-3" />
                          {action.label}
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* Error Details */}
                {agent.status === 'error' && agent.error_message && (
                  <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-2">
                    <p className="text-xs text-red-700 dark:text-red-400">
                      {agent.error_message}
                    </p>
                  </div>
                )}
              </div>
            </GlassCard>
            );
          })}
        </div>
      )}

      {/* Selected Agent Details */}
      {selectedAgent && (
        <GlassCard className="p-6">
          <div className="space-y-6">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-xl font-semibold text-foreground">
                  {friendlyNames[selectedAgent.id] ??
                    (selectedAgent.name ? friendlyNames[selectedAgent.name] : undefined) ??
                    selectedAgent.name}
                </h3>
                <p className="text-muted-foreground mt-1">{selectedAgent.description ?? 'No description available'}</p>
                {selectedAgent.current_task && (
                  <p className="text-sm text-blue-600 mt-1">Currently: {selectedAgent.current_task}</p>
                )}
              </div>
              <button
                onClick={() => setSelectedAgent(null)}
                className="text-muted-foreground hover:text-foreground"
              >
                ×
              </button>
            </div>

            {/* Configuration */}
            {selectedAgent.configuration && (
              <div>
                <h4 className="font-medium text-foreground mb-3">Configuration</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {Object.entries(selectedAgent.configuration).map(([key, value]) => (
                    <div key={key} className="bg-muted/20 rounded p-3">
                      <span className="text-sm font-medium text-foreground capitalize">
                        {key.replace('_', ' ')}
                      </span>
                      <p className="text-sm text-muted-foreground mt-1">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Capabilities */}
            {selectedAgent.capabilities && selectedAgent.capabilities.length > 0 && (
              <div>
                <h4 className="font-medium text-foreground mb-3">Capabilities</h4>
                <div className="flex flex-wrap gap-2">
                  {selectedAgent.capabilities.map((capability, index) => (
                    <span
                      key={index}
                      className="px-3 py-1 bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400 rounded-full text-sm"
                    >
                      {capability}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </GlassCard>
      )}
    </div>
  );
};

export default AgentStatusPanel;
