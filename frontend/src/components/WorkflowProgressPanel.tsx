// Workflow Progress Panel - Real-time orchestrator workflow tracking
// October 2025 - Dedicated progress visualization component

'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Zap, CheckCircle, AlertCircle, Clock, ArrowRight, Minimize2, BarChart3 } from 'lucide-react';
import GlassCard from './ui/GlassCard';
import { cn } from '../lib/utils';

interface WorkflowStep {
  id: string;
  name: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';
  progress_percentage?: number;
  start_time?: string;
  end_time?: string;
  duration_ms?: number;
  error_message?: string;
  results?: Record<string, unknown>;
  sub_steps?: WorkflowStep[];
}

interface WorkflowProgress {
  workflow_id: string;
  workflow_type: string;
  name: string;
  status: 'initializing' | 'running' | 'completed' | 'failed' | 'paused' | 'cancelled';
  overall_progress: number;
  current_step_index: number;
  total_steps: number;
  steps: WorkflowStep[];
  start_time: string;
  estimated_completion?: string;
  metadata?: Record<string, unknown>;
  performance_metrics?: {
    total_duration_ms?: number;
    steps_completed: number;
    steps_failed: number;
    average_step_duration_ms?: number;
  };
}

interface WorkflowProgressPanelProps {
  workflows: WorkflowProgress[];
  isMinimized?: boolean;
  onToggleMinimize?: () => void;
  onClearCompleted?: () => void;
  className?: string;
  maxHeight?: string;
}

const WorkflowProgressPanel: React.FC<WorkflowProgressPanelProps> = ({
  workflows,
  isMinimized = false,
  onToggleMinimize,
  onClearCompleted,
  className,
  maxHeight = 'max-h-96'
}) => {
  const [selectedWorkflow, setSelectedWorkflow] = useState<string | null>(null);
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
  const autoScrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest activity
  useEffect(() => {
    if (autoScrollRef.current) {
      autoScrollRef.current.scrollTop = autoScrollRef.current.scrollHeight;
    }
  }, [workflows]);

  const toggleStepExpansion = (stepId: string) => {
    const newExpanded = new Set(expandedSteps);
    if (newExpanded.has(stepId)) {
      newExpanded.delete(stepId);
    } else {
      newExpanded.add(stepId);
    }
    setExpandedSteps(newExpanded);
  };

  const getStatusIcon = (status: WorkflowStep['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-600" />;
      case 'failed':
        return <AlertCircle className="w-4 h-4 text-red-600" />;
      case 'in_progress':
        return <Zap className="w-4 h-4 text-blue-600 animate-pulse" />;
      case 'pending':
        return <Clock className="w-4 h-4 text-gray-400" />;
      case 'skipped':
        return <ArrowRight className="w-4 h-4 text-yellow-600" />;
      default:
        return <Clock className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusColor = (status: WorkflowProgress['status']) => {
    switch (status) {
      case 'completed':
        return 'text-green-600 bg-green-50 border-green-200';
      case 'failed':
        return 'text-red-600 bg-red-50 border-red-200';
      case 'running':
        return 'text-blue-600 bg-blue-50 border-blue-200';
      case 'paused':
        return 'text-yellow-600 bg-yellow-50 border-yellow-200';
      case 'cancelled':
        return 'text-gray-600 bg-gray-50 border-gray-200';
      default:
        return 'text-blue-600 bg-blue-50 border-blue-200';
    }
  };

  const formatDuration = (ms?: number) => {
    if (!ms) return 'N/A';
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) return `${hours}h ${minutes % 60}m`;
    if (minutes > 0) return `${minutes}m ${seconds % 60}s`;
    return `${seconds}s`;
  };

  const renderWorkflowStep = (step: WorkflowStep, depth = 0) => {
    const isExpanded = expandedSteps.has(step.id);
    const hasSubSteps = step.sub_steps && step.sub_steps.length > 0;

    return (
      <div key={step.id} className={cn("space-y-2", depth > 0 && "ml-6 border-l-2 border-gray-200 pl-4")}>
        <div className="flex items-center justify-between p-3 bg-white/60 backdrop-blur-sm rounded-lg border border-gray-200 hover:shadow-md transition-all duration-200">
          <div className="flex items-center space-x-3 flex-1">
            {getStatusIcon(step.status)}
            <div className="flex-1">
              <div className="flex items-center space-x-2">
                <span className="font-medium text-gray-900">{step.name}</span>
                {hasSubSteps && (
                  <button
                    onClick={() => toggleStepExpansion(step.id)}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    <ArrowRight className={cn("w-3 h-3 transition-transform", isExpanded && "rotate-90")} />
                  </button>
                )}
              </div>
              {step.error_message && (
                <p className="text-sm text-red-600 mt-1">{step.error_message}</p>
              )}
            </div>
          </div>
          <div className="flex items-center space-x-2 text-sm text-gray-500">
            {step.progress_percentage !== undefined && (
              <span>{step.progress_percentage}%</span>
            )}
            {step.duration_ms && (
              <span>{formatDuration(step.duration_ms)}</span>
            )}
          </div>
        </div>

        {/* Progress bar for in-progress steps */}
        {step.status === 'in_progress' && step.progress_percentage !== undefined && (
          <div className="w-full bg-gray-200 rounded-full h-2 ml-7">
            <div
              className="bg-gradient-to-r from-[#111111] to-[#FFD400] h-2 rounded-full transition-all duration-500"
              style={{ width: `${step.progress_percentage}%` }}
            />
          </div>
        )}

        {/* Sub-steps */}
        {hasSubSteps && isExpanded && step.sub_steps && (
          <div className="space-y-1">
            {step.sub_steps.map((subStep) => renderWorkflowStep(subStep, depth + 1))}
          </div>
        )}

        {/* Results display */}
        {step.results && isExpanded && (
          <div className="ml-7 p-2 bg-gray-50 rounded text-sm">
            <strong>Results:</strong>
            <pre className="mt-1 text-xs text-gray-600 overflow-x-auto">
              {JSON.stringify(step.results, null, 2)}
            </pre>
          </div>
        )}
      </div>
    );
  };

  const renderWorkflow = (workflow: WorkflowProgress) => {
    const isSelected = selectedWorkflow === workflow.workflow_id;

    return (
      <div key={workflow.workflow_id} className="space-y-3">
        <div
          className={cn(
            "p-4 rounded-xl border-2 cursor-pointer transition-all duration-200",
            getStatusColor(workflow.status),
            isSelected && "ring-2 ring-blue-300 shadow-lg"
          )}
          onClick={() => setSelectedWorkflow(isSelected ? null : workflow.workflow_id)}
        >
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <div className="flex items-center space-x-2 mb-2">
                <h3 className="font-semibold">{workflow.name}</h3>
                <span className="text-xs px-2 py-1 rounded-full bg-white/60">
                  {workflow.workflow_type}
                </span>
              </div>
              <div className="flex items-center space-x-4 text-sm">
                <span>Step {workflow.current_step_index + 1} of {workflow.total_steps}</span>
                <span>{workflow.overall_progress}% complete</span>
                {workflow.estimated_completion && (
                  <span>ETA: {new Date(workflow.estimated_completion).toLocaleTimeString()}</span>
                )}
              </div>
            </div>
            <div className="flex items-center space-x-2">
              {workflow.status === 'running' && (
                <Zap className="w-5 h-5 animate-pulse" />
              )}
              <ArrowRight className={cn("w-4 h-4 transition-transform", isSelected && "rotate-90")} />
            </div>
          </div>

          {/* Overall progress bar */}
          <div className="w-full bg-white/40 rounded-full h-2 mt-3">
            <div
              className="bg-gradient-to-r from-[#111111] to-[#FFD400] h-2 rounded-full transition-all duration-500"
              style={{ width: `${workflow.overall_progress}%` }}
            />
          </div>

          {/* Performance metrics */}
          {workflow.performance_metrics && isSelected && (
            <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
              <div className="text-center p-2 bg-white/40 rounded">
                <div className="font-medium">{workflow.performance_metrics.steps_completed}</div>
                <div className="text-gray-600">Completed</div>
              </div>
              <div className="text-center p-2 bg-white/40 rounded">
                <div className="font-medium">{workflow.performance_metrics.steps_failed}</div>
                <div className="text-gray-600">Failed</div>
              </div>
              <div className="text-center p-2 bg-white/40 rounded">
                <div className="font-medium">{formatDuration(workflow.performance_metrics.average_step_duration_ms)}</div>
                <div className="text-gray-600">Avg Step</div>
              </div>
            </div>
          )}
        </div>

        {/* Detailed steps view */}
        {isSelected && (
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {workflow.steps.map(step => renderWorkflowStep(step))}
          </div>
        )}
      </div>
    );
  };

  // Minimized floating button
  if (isMinimized) {
    const activeWorkflows = workflows.filter(w => w.status === 'running' || w.status === 'initializing');
    return (
      <div className="fixed bottom-20 right-4 z-40">
        <button
          onClick={onToggleMinimize}
          className={cn(
            "w-14 h-14 rounded-full text-white shadow-lg hover:shadow-xl transition-all duration-200 flex items-center justify-center relative",
            activeWorkflows.length > 0
              ? "bg-gradient-to-r from-[#111111] to-[#FFD400] animate-pulse"
              : "bg-gradient-to-r from-gray-500 to-gray-600"
          )}
        >
          <BarChart3 className="w-6 h-6" />
          {activeWorkflows.length > 0 && (
            <div className="absolute -top-2 -right-2 w-6 h-6 bg-green-500 rounded-full flex items-center justify-center text-xs font-bold">
              {activeWorkflows.length}
            </div>
          )}
        </button>
      </div>
    );
  }

  return (
    <GlassCard className={cn("flex flex-col", maxHeight, className)}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/20 bg-gradient-to-r from-slate-50/80 to-emerald-50/80 backdrop-blur-sm">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-r from-[#111111] to-[#FFD400] flex items-center justify-center shadow-lg">
            <BarChart3 className="w-5 h-5 text-white" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 text-lg">Workflow Progress</h3>
            <p className="text-sm text-gray-600">
              {workflows.filter(w => w.status === 'running').length} active, {workflows.filter(w => w.status === 'completed').length} completed
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-2">
          {onClearCompleted && workflows.some(w => w.status === 'completed') && (
            <button
              onClick={onClearCompleted}
              className="text-gray-400 hover:text-gray-600 text-sm"
            >
              Clear Completed
            </button>
          )}
          {onToggleMinimize && (
            <button
              onClick={onToggleMinimize}
              className="p-1 rounded-full hover:bg-white/20 transition-colors duration-200"
            >
              <Minimize2 className="w-4 h-4 text-gray-600" />
            </button>
          )}
        </div>
      </div>

      {/* Workflows List */}
      <div ref={autoScrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {workflows.length === 0 ? (
          <div className="text-center py-8">
            <BarChart3 className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500">No active workflows</p>
            <p className="text-sm text-gray-400">Workflows will appear here when Link starts processing requests</p>
          </div>
        ) : (
          workflows.map(workflow => renderWorkflow(workflow))
        )}
      </div>
    </GlassCard>
  );
};

export default WorkflowProgressPanel;
