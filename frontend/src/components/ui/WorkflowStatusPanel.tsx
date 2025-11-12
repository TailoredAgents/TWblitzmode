// WorkflowStatusPanel - Real-Time Workflow Progress Display
// Integrates with WebSocket progress notifications for live workflow updates

'use client';

import React, { useState, useEffect, useMemo } from 'react';
import {
  Activity,
  CheckCircle,
  AlertCircle,
  Clock,
  Zap,
  X,
  Play,
  Square,
  Loader2
} from 'lucide-react';
import GlassCard from './GlassCard';
import { cn, stringifyId } from '../../lib/utils';
import webSocketService from '../../services/websocket';

type WorkflowDetailRecord = Record<string, unknown>;

interface WorkflowProgress {
  type: 'workflow_progress';
  status: 'started' | 'in_progress' | 'completed' | 'failed' | 'cancelled';
  workflow_type: string;
  workflow_id: string;
  progress_percentage: number | string;
  current_step: number | string;
  total_steps: number | string;
  message: string;
  timestamp: string;
  results?: WorkflowDetailRecord;
  error_details?: WorkflowDetailRecord;
  metadata?: WorkflowDetailRecord;
}

interface WorkflowStatusPanelProps {
  organizationId: number | string;
  userId: number | string;
  className?: string;
  onClose?: () => void;
  showHeader?: boolean;
  maxItems?: number;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const normalizeWorkflowProgress = (input: unknown): WorkflowProgress | null => {
  if (!isRecord(input)) {
    return null;
  }

  const statusRaw = typeof input['status'] === 'string' ? input['status'].toLowerCase() : 'started';
  const allowedStatuses: WorkflowProgress['status'][] = [
    'started',
    'in_progress',
    'completed',
    'failed',
    'cancelled',
  ];
  const status = allowedStatuses.includes(statusRaw as WorkflowProgress['status'])
    ? (statusRaw as WorkflowProgress['status'])
    : 'started';

  const idCandidate = [input['workflow_id'], input['execution_id'], input['id'], input['run_id']].find(
    (value): value is string | number => typeof value === 'string' || typeof value === 'number'
  );
  const workflowId = stringifyId(idCandidate);
  if (!workflowId) {
    return null;
  }

  const workflowType =
    typeof input['workflow_type'] === 'string' ? (input['workflow_type'] as string) : 'autonomous';
  const timestamp =
    typeof input['timestamp'] === 'string' ? (input['timestamp'] as string) : new Date().toISOString();
  const progressSource =
    input['progress_percentage'] ?? input['progress'] ?? input['completion'] ?? 0;
  const currentStepSource = input['current_step'] ?? input['step'];
  const totalStepsSource = input['total_steps'] ?? input['max_steps'];
  const message = typeof input['message'] === 'string' ? (input['message'] as string) : '';

  const normalized: WorkflowProgress = {
    type: 'workflow_progress',
    status,
    workflow_type: workflowType,
    workflow_id: workflowId,
    progress_percentage:
      typeof progressSource === 'number' || typeof progressSource === 'string' ? progressSource : 0,
    current_step:
      typeof currentStepSource === 'number' || typeof currentStepSource === 'string'
        ? currentStepSource
        : 0,
    total_steps:
      typeof totalStepsSource === 'number' || typeof totalStepsSource === 'string'
        ? totalStepsSource
        : 0,
    message,
    timestamp,
  };
  if (isRecord(input['results'])) {
    normalized.results = input['results'] as WorkflowDetailRecord;
  }
  if (isRecord(input['error_details'])) {
    normalized.error_details = input['error_details'] as WorkflowDetailRecord;
  }
  if (isRecord(input['metadata'])) {
    normalized.metadata = input['metadata'] as WorkflowDetailRecord;
  }
  return normalized;
};

const extractErrorMessage = (details?: WorkflowDetailRecord): string => {
  if (!details || !isRecord(details)) {
    return 'An error occurred';
  }
  const messageCandidate = details['message'];
  return typeof messageCandidate === 'string' && messageCandidate.trim().length > 0
    ? messageCandidate
    : 'An error occurred';
};

const WorkflowStatusPanel: React.FC<WorkflowStatusPanelProps> = ({
  organizationId,
  userId: _userId,
  className,
  onClose,
  showHeader = true,
  maxItems = 5
}) => {
  const organizationKey = useMemo(() => stringifyId(organizationId), [organizationId]);
  const [activeWorkflows, setActiveWorkflows] = useState<WorkflowProgress[]>([]);
  const [completedWorkflows, setCompletedWorkflows] = useState<WorkflowProgress[]>([]);
  const [showCompleted, setShowCompleted] = useState(false);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    // Set up WebSocket listeners for workflow progress
    const handleWorkflowProgress = (raw: unknown) => {
      const data = normalizeWorkflowProgress(raw);
      if (!data) {
        return;
      }
      if (data.status === 'started' || data.status === 'in_progress') {
        // Update or add to active workflows
        setActiveWorkflows((prev) => {
          const existing = prev.find((workflow) => workflow.workflow_id === data.workflow_id);
          if (existing) {
            return prev.map((workflow) =>
              workflow.workflow_id === data.workflow_id ? data : workflow
            );
          }
          return [...prev, data];
        });
      } else if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
        // Move to completed workflows
        setActiveWorkflows(prev => prev.filter(w => w.workflow_id !== data.workflow_id));
        setCompletedWorkflows(prev => {
          const updated = [data, ...prev.slice(0, maxItems - 1)];
          return updated;
        });
      }
    };

    const handleConnectionChange = () => {
      setIsConnected(webSocketService.isConnectedToServer());
    };

    // Set up listeners
    webSocketService.on('workflow_progress', handleWorkflowProgress);
    webSocketService.on('connect', handleConnectionChange);
    webSocketService.on('disconnect', handleConnectionChange);

    // Initial connection state
    setIsConnected(webSocketService.isConnectedToServer());

    // Connect if not already connected
    if (organizationKey && !webSocketService.isConnectedToServer()) {
      webSocketService.connect();
      webSocketService.joinOrganizationRoom(organizationKey);
    }

    return () => {
      webSocketService.off('workflow_progress', handleWorkflowProgress);
      webSocketService.off('connect', handleConnectionChange);
      webSocketService.off('disconnect', handleConnectionChange);
    };
  }, [organizationKey, maxItems]);

  const getStatusIcon = (status: WorkflowProgress['status']) => {
    switch (status) {
      case 'started':
        return <Play className="w-4 h-4 text-blue-500" />;
      case 'in_progress':
        return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'failed':
        return <AlertCircle className="w-4 h-4 text-red-500" />;
      case 'cancelled':
        return <Square className="w-4 h-4 text-gray-500" />;
      default:
        return <Clock className="w-4 h-4 text-gray-500" />;
    }
  };

  const getStatusColor = (status: WorkflowProgress['status']) => {
    switch (status) {
      case 'started':
      case 'in_progress':
        return 'text-blue-600 bg-blue-50 border-blue-200';
      case 'completed':
        return 'text-green-600 bg-green-50 border-green-200';
      case 'failed':
        return 'text-red-600 bg-red-50 border-red-200';
      case 'cancelled':
        return 'text-gray-600 bg-gray-50 border-gray-200';
      default:
        return 'text-gray-600 bg-gray-50 border-gray-200';
    }
  };

  const formatWorkflowName = (workflowType: string) => {
    return workflowType
      .replace(/_/g, ' ')
      .replace(/\b\w/g, l => l.toUpperCase());
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString();
  };

  const renderProgressBar = (workflow: WorkflowProgress) => {
    const percentage = typeof workflow.progress_percentage === 'number'
      ? workflow.progress_percentage
      : 0;

    if (workflow.status === 'failed' || workflow.status === 'cancelled') {
      return null;
    }

    return (
      <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
        <div
          className={cn(
            "h-2 rounded-full transition-all duration-500",
            workflow.status === 'completed'
              ? "bg-green-500"
              : "bg-blue-500"
          )}
          style={{ width: `${Math.min(percentage, 100)}%` }}
        />
      </div>
    );
  };

  const renderWorkflowItem = (workflow: WorkflowProgress) => (
    <div key={workflow.workflow_id} className="border-b border-border/20 last:border-b-0 pb-4 last:pb-0">
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 mt-1">
          {getStatusIcon(workflow.status)}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <h4 className="text-sm font-medium text-foreground truncate">
              {formatWorkflowName(workflow.workflow_type)}
            </h4>
            <div className="flex items-center gap-2">
              <span className={cn(
                'px-2 py-1 rounded-full text-xs font-medium border',
                getStatusColor(workflow.status)
              )}>
                {workflow.status}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatTimestamp(workflow.timestamp)}
              </span>
            </div>
          </div>

          <p className="text-sm text-muted-foreground mb-2">
            {workflow.message}
          </p>

          {/* Step indicator */}
          {typeof workflow.current_step === 'number' && typeof workflow.total_steps === 'number' && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
              <span>Step {workflow.current_step} of {workflow.total_steps}</span>
              {typeof workflow.progress_percentage === 'number' && (
                <span>• {workflow.progress_percentage}%</span>
              )}
            </div>
          )}

          {/* Progress bar */}
          {renderProgressBar(workflow)}

          {/* Results or error details */}
          {workflow.results && Object.keys(workflow.results).length > 0 && (
            <div className="mt-2 p-2 bg-green-50 border border-green-200 rounded text-xs">
              <span className="font-medium text-green-800">Results:</span>
              <span className="text-green-700 ml-1">
                {Object.keys(workflow.results).length} items generated
              </span>
            </div>
          )}

          {workflow.error_details && Object.keys(workflow.error_details).length > 0 && (
            <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs">
              <span className="font-medium text-red-800">Error:</span>
              <span className="text-red-700 ml-1">{extractErrorMessage(workflow.error_details)}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );

  const hasAnyWorkflows = activeWorkflows.length > 0 || completedWorkflows.length > 0;

  if (!hasAnyWorkflows && !isConnected) {
    return (
      <GlassCard className={cn("p-4", className)}>
        <div className="text-center text-muted-foreground">
          <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">Connecting to workflow updates...</p>
        </div>
      </GlassCard>
    );
  }

  if (!hasAnyWorkflows) {
    return (
      <GlassCard className={cn("p-4", className)}>
        <div className="text-center text-muted-foreground">
          <Zap className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No active workflows</p>
          <p className="text-xs mt-1">Workflow progress will appear here</p>
        </div>
      </GlassCard>
    );
  }

  return (
    <GlassCard className={cn("", className)}>
      {showHeader && (
        <div className="flex items-center justify-between p-4 border-b border-border/20">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-foreground">Workflow Progress</h3>
            <div className={cn(
              "w-2 h-2 rounded-full",
              isConnected ? "bg-green-500" : "bg-red-500"
            )} />
          </div>

          <div className="flex items-center gap-2">
            {completedWorkflows.length > 0 && (
              <button
                onClick={() => setShowCompleted(!showCompleted)}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                {showCompleted ? 'Hide' : 'Show'} completed ({completedWorkflows.length})
              </button>
            )}

            {onClose && (
              <button
                onClick={onClose}
                className="p-1 rounded hover:bg-muted/20 transition-colors"
              >
                <X className="w-4 h-4 text-muted-foreground" />
              </button>
            )}
          </div>
        </div>
      )}

      <div className="p-4 space-y-4 max-h-96 overflow-y-auto">
        {/* Active Workflows */}
        {activeWorkflows.length > 0 && (
          <div>
            {!showHeader && activeWorkflows.length > 0 && (
              <h4 className="text-sm font-medium text-foreground mb-3">Active Workflows</h4>
            )}
            <div className="space-y-4">
              {activeWorkflows.map(renderWorkflowItem)}
            </div>
          </div>
        )}

        {/* Completed Workflows */}
        {showCompleted && completedWorkflows.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-foreground mb-3">Recently Completed</h4>
            <div className="space-y-4">
              {completedWorkflows.slice(0, maxItems).map(renderWorkflowItem)}
            </div>
          </div>
        )}
      </div>
    </GlassCard>
  );
};

export default WorkflowStatusPanel;
