// Autonomous AI Workflows - September 2025 AI Integration
// Zero-click autonomous prospecting and workflow automation

'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  type LucideIcon,
  Play,
  Pause,
  Square,
  Settings,
  Activity,
  Bot,
  Zap,
  CheckCircle,
  AlertTriangle,
  Clock,
  TrendingUp,
  Users,
  Mail,
  Database,
  RefreshCw,
} from 'lucide-react';
import GlassCard from './ui/GlassCard';
import { CardSkeleton } from './ui/LoadingSkeleton';
import { useToastActions } from './ui/ToastContainer';
import { apiService } from '../services/api';
import { cn, stringifyId } from '../lib/utils';
import type { AIWorkflow } from '../types';

interface AutonomousWorkflowsProps {
  organizationId: number | string;
  tenantId?: number | string;
}

interface WorkflowTemplateCard {
  id: string;
  name: string;
  description: string;
  type: 'prospecting' | 'outreach' | 'follow_up' | 'research' | 'qualification';
  icon: LucideIcon;
  estimatedTime: string;
  requirements: string[];
  autonomous: boolean;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const coerceNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }
  if (typeof value === 'string') {
    const cleaned = value.replace(/[^0-9.-]/g, '');
    if (!cleaned) {
      return undefined;
    }
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
};

export interface WorkflowDisplayMetrics {
  executions?: number;
  successRate?: number;
  resultsGenerated?: number;
  costSavings?: number;
  prospectsProcessed?: number;
  connectorsFound?: number;
  emailsScheduled?: number;
}

type RawWorkflowRecord = {
  workflow_id?: string | number | null;
  id?: string | number | null;
  execution_id?: string | number | null;
  workflowId?: string | number | null;
  status?: string;
  organization_id?: string | number | null;
  initiated_by?: string | number | null;
  initiatedBy?: string | number | null;
  user_id?: string | number | null;
  result?: unknown;
  metrics?: unknown;
  prospects_processed?: unknown;
  prospectsProcessed?: unknown;
  total_prospects_processed?: unknown;
  connectors_found?: unknown;
  connectorsFound?: unknown;
  total_connectors_found?: unknown;
  emails_scheduled?: unknown;
  emailsScheduled?: unknown;
  total_emails_scheduled?: unknown;
  total_cost_savings?: unknown;
  cost_savings?: unknown;
  success_rate?: unknown;
  success_rate_percent?: unknown;
  completion_rate_percent?: unknown;
  completed_workflows?: unknown;
  completed_runs?: unknown;
  completed?: unknown;
  total_workflows?: unknown;
  total_runs?: unknown;
  total?: unknown;
  executions?: unknown;
  execution_count?: unknown;
  run_count?: unknown;
  runs?: unknown;
  pending_approvals?: unknown;
  pendingApprovals?: unknown;
  input_data?: unknown;
  context_data?: unknown;
  metadata?: unknown;
  created_at?: unknown;
  createdAt?: unknown;
  updated_at?: unknown;
  updatedAt?: unknown;
  type?: unknown;
  workflow_type?: unknown;
  autonomous?: unknown;
  auto_mode?: unknown;
  [key: string]: unknown;
};

const readRecord = (value: unknown): Record<string, unknown> => (isRecord(value) ? value : {});

export const deriveWorkflowMetrics = (workflow: AIWorkflow): WorkflowDisplayMetrics => {
  const baseResult = readRecord(workflow.result);
  const nestedResultMetrics = readRecord(baseResult['metrics']);
  const inputMetricsContainer = readRecord(workflow.input_data);
  const inputMetrics = readRecord(inputMetricsContainer['metrics']);

  const combinedMap = new Map<string, unknown>();
  const mergeIntoCombined = (source: Record<string, unknown>) => {
    Object.entries(source).forEach(([key, value]) => {
      if (value !== undefined) {
        combinedMap.set(key, value);
      }
    });
  };

  mergeIntoCombined(inputMetrics);
  mergeIntoCombined(baseResult);
  mergeIntoCombined(nestedResultMetrics);

  const workflowMap = new Map<string, unknown>(
    Object.entries(workflow as unknown as Record<string, unknown>)
  );

  const collect = (keys: readonly string[]): number | undefined => {
    for (const key of keys) {
      if (!combinedMap.has(key) && workflowMap.has(key)) {
        combinedMap.set(key, workflowMap.get(key));
      }
      if (!combinedMap.has(key)) {
        continue;
      }
      const parsed = coerceNumber(combinedMap.get(key));
      if (parsed !== undefined) {
        return parsed;
      }
    }
    return undefined;
  };

  const executions =
    collect(['executions', 'execution_count', 'run_count', 'runs', 'total_runs', 'completed_runs']) ??
    collect(['total_workflows', 'total', 'workflow_count']);

  const prospectsProcessed = collect(['prospects_processed', 'prospectsProcessed', 'total_prospects_processed']);
  const connectorsFound = collect(['connectors_found', 'connectorsFound', 'total_connectors_found']);
  const emailsScheduled = collect(['emails_scheduled', 'emailsScheduled', 'total_emails_scheduled']);
  const resultsGenerated =
    collect([
      'results_generated',
      'resultsGenerated',
      'matches_found',
      'introductions_generated',
      'tasks_completed',
    ]) ?? connectorsFound ?? emailsScheduled;

  let successRate = collect([
    'success_rate_percent',
    'success_rate',
    'successRate',
    'completion_rate_percent',
    'completion_rate',
    'win_rate',
  ]);

  if (successRate !== undefined && successRate <= 1) {
    successRate = Math.round(successRate * 100);
  } else if (successRate !== undefined) {
    successRate = Math.round(successRate);
  }

  if (successRate === undefined) {
    const completed = collect(['completed_workflows', 'completed_runs', 'completed']);
    const total = collect(['total_workflows', 'total_runs', 'total', 'executions']);
    if (completed !== undefined && total && total > 0) {
      successRate = Math.round((completed / total) * 100);
    }
  }

  const costSavings = collect(['cost_savings', 'costSavings', 'cost_saved', 'savings', 'estimated_cost_savings']);

  const metrics: WorkflowDisplayMetrics = {};
  if (executions !== undefined) {
    metrics.executions = executions;
  }
  if (successRate !== undefined) {
    metrics.successRate = successRate;
  }
  if (resultsGenerated !== undefined) {
    metrics.resultsGenerated = resultsGenerated;
  }
  if (costSavings !== undefined) {
    metrics.costSavings = costSavings;
  }
  if (prospectsProcessed !== undefined) {
    metrics.prospectsProcessed = prospectsProcessed;
  }
  if (connectorsFound !== undefined) {
    metrics.connectorsFound = connectorsFound;
  }
  if (emailsScheduled !== undefined) {
    metrics.emailsScheduled = emailsScheduled;
  }

  return metrics;
};

const currencyFormatter =
  typeof Intl !== 'undefined'
    ? new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : null;

const extractErrorMessage = (value: unknown): string | undefined => {
  if (value instanceof Error) {
    return value.message;
  }
  if (isRecord(value) && isRecord(value.response) && isRecord(value.response.data)) {
    const detail = value.response.data;
    if (typeof detail.message === 'string' && detail.message.trim().length > 0) {
      return detail.message;
    }
  }
  return undefined;
};

const formatCurrency = (value: number): string => {
  if (!currencyFormatter) {
    return `$${value.toFixed(0)}`;
  }
  return currencyFormatter.format(value);
};

const AutonomousWorkflows: React.FC<AutonomousWorkflowsProps> = ({ organizationId, tenantId }) => {
  const [workflows, setWorkflows] = useState<AIWorkflow[]>([]);
  const [templates, setTemplates] = useState<WorkflowTemplateCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'running' | 'templates' | 'analytics'>('running');
  const [autoMode, setAutoMode] = useState(false);
  const { success, error } = useToastActions();
  const organizationKey = useMemo(() => stringifyId(organizationId), [organizationId]);
  const tenantKey = useMemo(() => stringifyId(tenantId ?? organizationId), [tenantId, organizationId]);

  const normalizeWorkflow = useCallback((workflow: unknown): AIWorkflow | null => {
    if (!isRecord(workflow)) {
      return null;
    }

    const raw = workflow as RawWorkflowRecord;
    const workflowIdCandidates: Array<string | number | null | undefined> = [
      raw.workflow_id,
      raw.id,
      raw.execution_id,
      raw.workflowId,
    ];
    const workflowId = workflowIdCandidates
      .map((candidate) => stringifyId(candidate))
      .find((value): value is string => Boolean(value));

    if (!workflowId) {
      return null;
    }

    const rawStatusValue = raw.status;
    const rawStatus = typeof rawStatusValue === 'string' ? rawStatusValue.toLowerCase() : 'initiated';
    const statusMap = new Map<string, AIWorkflow['status']>([
      ['running', 'approved'],
      ['paused', 'pending_approval'],
      ['completed', 'completed'],
      ['failed', 'failed'],
      ['pending', 'pending_approval'],
      ['approved', 'approved'],
      ['rejected', 'rejected'],
      ['initiated', 'initiated'],
    ]);

    const workflowOrgId =
      stringifyId(raw.organization_id) ??
      organizationKey ??
      tenantKey ??
      'unknown';

    const workflowUserId =
      stringifyId(raw.user_id) ??
      stringifyId(raw.initiated_by) ??
      stringifyId(raw.initiatedBy) ??
      'unknown';

    const rawResult = readRecord(raw.result);
    const nestedResultMetrics = readRecord(rawResult.metrics);
    if ('metrics' in rawResult) {
      delete rawResult.metrics;
    }
    const rawMetrics = readRecord(raw.metrics);

    const aggregatedResult: Record<string, unknown> = {
      ...rawResult,
      ...nestedResultMetrics,
      ...rawMetrics,
    };

    const prospectedValue =
      raw.prospects_processed ?? raw.prospectsProcessed ?? raw.total_prospects_processed;
    if (prospectedValue !== undefined) {
      aggregatedResult.prospects_processed = prospectedValue;
    }

    const connectorsValue = raw.connectors_found ?? raw.connectorsFound ?? raw.total_connectors_found;
    if (connectorsValue !== undefined) {
      aggregatedResult.connectors_found = connectorsValue;
    }

    const emailsValue = raw.emails_scheduled ?? raw.emailsScheduled ?? raw.total_emails_scheduled;
    if (emailsValue !== undefined) {
      aggregatedResult.emails_scheduled = emailsValue;
    }

    const totalCostSavings = raw.total_cost_savings;
    const costSavings = raw.cost_savings;
    if (totalCostSavings !== undefined) {
      aggregatedResult.cost_savings = totalCostSavings;
    } else if (costSavings !== undefined) {
      aggregatedResult.cost_savings = costSavings;
    }

    const successRateValue = raw.success_rate ?? raw.success_rate_percent;
    const completionRateValue = raw.completion_rate_percent;
    if (successRateValue !== undefined) {
      aggregatedResult.success_rate = successRateValue;
    } else if (completionRateValue !== undefined) {
      aggregatedResult.success_rate = completionRateValue;
    }

    const executionCandidate =
      raw.executions ??
      raw.execution_count ??
      raw.run_count ??
      raw.total_runs ??
      raw.runs;
    if (executionCandidate !== undefined) {
      aggregatedResult.executions = executionCandidate;
    }

    const pendingApprovals = Array.isArray(raw.pending_approvals)
      ? (raw.pending_approvals as unknown[]).map((item) => String(item))
      : Array.isArray(raw.pendingApprovals)
        ? (raw.pendingApprovals as unknown[]).map((item) => String(item))
        : [];

    const inputData = readRecord(raw.input_data ?? raw.context_data ?? raw.metadata);

    const createdAtRaw = raw.created_at ?? raw.createdAt;
    const updatedAtRaw = raw.updated_at ?? raw.updatedAt ?? createdAtRaw;

    const typeCandidate = raw.type ?? raw.workflow_type;
    const workflowType = typeof typeCandidate === 'string'
      ? (typeCandidate as AIWorkflow['type'])
      : 'prospect_analysis';

    return {
      workflow_id: workflowId,
      type: workflowType,
      status: statusMap.get(rawStatus) ?? 'initiated',
      organization_id: workflowOrgId,
      user_id: workflowUserId,
      input_data: inputData,
      result: aggregatedResult,
      pending_approvals: pendingApprovals,
      created_at: typeof createdAtRaw === 'string' ? createdAtRaw : new Date().toISOString(),
      updated_at: typeof updatedAtRaw === 'string' ? updatedAtRaw : new Date().toISOString(),
    };
  }, [organizationKey, tenantKey]);

  const loadWorkflows = useCallback(async () => {
    if (!tenantKey) {
      error('Failed to load workflows', 'The organization identifier is missing or invalid.');
      setWorkflows([]);
      return;
    }
    try {
      setLoading(true);
      const [corporateResponse, activeResponse] = await Promise.all([
        apiService.getCorporateWorkflows(tenantKey).catch(() => ({ data: { workflows: [] } })),
        apiService.getActiveWorkflows(tenantKey).catch(() => ({ data: { workflows: [] } })),
      ]);

      const combined = [
        ...(corporateResponse.data?.workflows ?? []),
        ...(activeResponse.data?.workflows ?? []),
      ];

      const normalized = combined
        .map((workflow) => normalizeWorkflow(workflow))
        .filter((workflow): workflow is AIWorkflow => Boolean(workflow?.workflow_id));

      // Deduplicate by workflow_id
      const uniqueMap = new Map<string, AIWorkflow>();
      normalized.forEach((workflow) => {
        uniqueMap.set(workflow.workflow_id, workflow);
      });

      setWorkflows(Array.from(uniqueMap.values()));
    } catch (err) {
      console.error('Failed to load workflows:', err);
      error('Failed to load workflows');
    } finally {
      setLoading(false);
    }
  }, [tenantKey, error, normalizeWorkflow]);

  const loadTemplates = useCallback(async () => {
    if (!tenantKey) {
      error('Failed to load workflow templates', 'The organization identifier is missing or invalid.');
      setTemplates([]);
      return;
    }
    try {
      setLoading(true);
      const response = await apiService.getWorkflowTemplates(tenantKey);
      const templateData = response.data?.templates ?? [];
      const templateRecords = Array.isArray(templateData)
        ? templateData.filter(isRecord)
        : [];

      const normalizedTemplates: WorkflowTemplateCard[] = templateRecords.map((template) => {
        const templateType =
          (typeof template.category === 'string'
            ? (template.category as WorkflowTemplateCard['type'])
            : 'prospecting');
        const metricsRecord = isRecord(template.metrics) ? template.metrics : {};
        const configurationRecord = isRecord(template.configuration) ? template.configuration : {};

        return {
          id: String(
            template.id ??
              template.name ??
              template.category ??
              Date.now()
          ),
          name: typeof template.name === 'string' ? template.name : 'Autonomous Workflow',
          description:
            typeof template.description === 'string'
              ? template.description
              : 'Autonomous workflow template',
          type: templateType,
          icon: getTemplateIcon(templateType),
          estimatedTime:
            (typeof metricsRecord['avg_time'] === 'string'
              ? (metricsRecord['avg_time'] as string)
              : typeof template.estimatedTime === 'string'
                ? template.estimatedTime
                : '30 minutes'),
          requirements: Array.isArray(template.requirements)
            ? (template.requirements as string[])
            : Array.isArray(configurationRecord['requirements'])
              ? (configurationRecord['requirements'] as string[])
              : [],
          autonomous: typeof template.autonomous === 'boolean' ? template.autonomous : true,
        };
      });

      setTemplates(normalizedTemplates);
    } catch (err) {
      console.error('Failed to load workflow templates:', err);
      error('Failed to load workflow templates', 'Please check your connection and try again');
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, [tenantKey, error]);

  useEffect(() => {
    void loadWorkflows();
    void loadTemplates();
  }, [loadWorkflows, loadTemplates]);

  // Helper function to map template types to icons
  const getTemplateIcon = (type: string | undefined): LucideIcon => {
    switch (type) {
      case 'prospecting': return Users;
      case 'outreach': return Mail;
      case 'qualification': return TrendingUp;
      case 'research': return Database;
      case 'follow_up': return RefreshCw;
      default: return Bot;
    }
  };

  const mapTemplateToWorkflowType = (type: WorkflowTemplateCard['type']): string => {
    switch (type) {
      case 'prospecting':
      case 'qualification':
        return 'prospect_upload';
      case 'outreach':
      case 'follow_up':
        return 'automated_outreach';
      case 'research':
        return 'linkedin_scraping';
      default:
        return 'automated_outreach';
    }
  };

  const startWorkflow = async (templateId: string) => {
    if (!tenantKey) {
      error('Unable to start workflow', 'The organization identifier is missing or invalid.');
      return;
    }
    try {
      const template = templates.find(t => t.id === templateId);
      if (!template) return;

      const workflowData = {
        workflow_type: mapTemplateToWorkflowType(template.type),
        template_id: templateId,
        name: template.name,
        context_data: {
          autonomous: true,
          organization_id: organizationKey ?? organizationId,
          triggers: ['schedule'],
          approval_required: false,
        },
      };

      const response = await apiService.startWorkflow(tenantKey, workflowData);
      let createdWorkflowId: string | null = null;
      if (isRecord(response)) {
        createdWorkflowId = stringifyId(response['workflow_id'] as string | number | null | undefined);
        if (!createdWorkflowId && isRecord(response['data'])) {
          createdWorkflowId = stringifyId(
            (response['data'] as Record<string, unknown>)['workflow_id'] as string | number | null | undefined
          );
        }
      }
      if (createdWorkflowId) {
        success(`Started ${template.name}`, 'Autonomous workflow is now running');
        loadWorkflows(); // Refresh the workflows list
      }
    } catch (err) {
      console.error('Failed to start workflow:', err);
      error('Failed to start workflow');
    }
  };

  const stopWorkflow = async (workflowId: string) => {
    if (!workflowId) return;
    if (!tenantKey) {
      error('Unable to stop workflow', 'The organization identifier is missing or invalid.');
      return;
    }

    try {
      await apiService.stopWorkflow(tenantKey, workflowId);
      success('Workflow stopped', 'Autonomous workflow has been stopped');
      loadWorkflows();
    } catch (err) {
      console.error('Failed to stop workflow:', err);
      const message = extractErrorMessage(err) ?? 'Failed to stop workflow';
      error(message, 'Please try again or contact support if the issue persists.');
    }
  };

  const getWorkflowStatusIcon = (status: AIWorkflow['status']) => {
    switch (status) {
      case 'initiated':
      case 'approved':
        return <Play className="w-4 h-4 text-green-500" />;
      case 'pending_approval':
        return <Pause className="w-4 h-4 text-yellow-500" />;
      case 'rejected':
      case 'failed':
        return <AlertTriangle className="w-4 h-4 text-red-500" />;
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-500" />;
      default:
        return <Clock className="w-4 h-4 text-blue-500" />;
    }
  };

  const renderRunningWorkflows = () => {
    if (loading) {
      return (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      );
    }

    if (workflows.length === 0) {
      return (
        <GlassCard className="text-center py-12">
          <Bot className="w-16 h-16 text-muted-foreground mx-auto mb-4" />
          <h3 className="text-xl font-semibold text-foreground mb-2">No Active Workflows</h3>
          <p className="text-muted-foreground mb-6">Start an autonomous workflow to begin zero-click prospecting</p>
          <button
            onClick={() => setActiveTab('templates')}
            className="px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          >
            Browse Templates
          </button>
        </GlassCard>
      );
    }

    return (
      <div className="space-y-4">
        {workflows.map((workflow) => {
          const metrics = deriveWorkflowMetrics(workflow);
          const workflowResult: Record<string, unknown> = workflow.result ?? {};
          const executionsValue =
            metrics.executions ??
            metrics.prospectsProcessed ??
            coerceNumber(workflowResult['executions']);
          const executionsDisplay =
            executionsValue !== undefined ? Math.round(executionsValue).toLocaleString() : '—';

          const boundedSuccessRate =
            metrics.successRate !== undefined
              ? Math.max(0, Math.min(100, Math.round(metrics.successRate)))
              : undefined;
          const successRateDisplay = boundedSuccessRate !== undefined ? `${boundedSuccessRate}%` : '—';

          const resultsValue =
            metrics.resultsGenerated ?? metrics.connectorsFound ?? metrics.emailsScheduled;
          const resultItems = workflowResult['items'];
          const fallbackResultsCount = Array.isArray(resultItems)
            ? resultItems.length
            : undefined;
          const resultsDisplay =
            resultsValue !== undefined
              ? Math.round(resultsValue).toLocaleString()
              : fallbackResultsCount !== undefined
                ? fallbackResultsCount.toLocaleString()
                : '—';

          const costDisplay =
            metrics.costSavings !== undefined ? formatCurrency(metrics.costSavings) : '—';

          return (
            <GlassCard key={workflow.workflow_id} className="p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                {getWorkflowStatusIcon(workflow.status)}
                <div>
                  <h3 className="font-semibold text-foreground">
                    {typeof workflow.input_data?.name === 'string' && workflow.input_data.name.trim().length > 0
                      ? workflow.input_data.name
                      : workflow.type}
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    Running since {new Date(workflow.created_at).toLocaleDateString()}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <span className={cn(
                  'px-3 py-1 rounded-full text-xs font-medium',
                  (workflow.status === 'initiated' || workflow.status === 'approved') ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' :
                  workflow.status === 'pending_approval' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400' :
                  'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400'
                )}>
                  {workflow.status}
                </span>

                {(workflow.status === 'initiated' || workflow.status === 'approved') && (
                  <button
                    onClick={() => stopWorkflow(workflow.workflow_id)}
                    className="p-2 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/20 text-red-600 transition-colors"
                    title="Stop Workflow"
                  >
                    <Square className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>

            {/* Workflow Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <div className="text-center p-3 bg-muted/20 rounded-lg">
                <div className="text-2xl font-bold text-foreground">
                  {executionsDisplay}
                </div>
                <div className="text-xs text-muted-foreground">Executions</div>
              </div>
              <div className="text-center p-3 bg-muted/20 rounded-lg">
                <div className="text-2xl font-bold text-green-600">
                  {successRateDisplay}
                </div>
                <div className="text-xs text-muted-foreground">Success Rate</div>
              </div>
              <div className="text-center p-3 bg-muted/20 rounded-lg">
                <div className="text-2xl font-bold text-blue-600">
                  {resultsDisplay}
                </div>
                <div className="text-xs text-muted-foreground">Results</div>
              </div>
              <div className="text-center p-3 bg-muted/20 rounded-lg">
                <div className="text-2xl font-bold text-primary">
                  {costDisplay}
                </div>
                <div className="text-xs text-muted-foreground">Cost Saved</div>
              </div>
            </div>

            {/* Last Activity */}
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Activity className="w-4 h-4" />
              <span>Last activity: {new Date(workflow.updated_at).toLocaleString()}</span>
            </div>
          </GlassCard>
          );
        })}
      </div>
    );
  };

  const renderTemplates = () => {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-foreground">Autonomous Workflow Templates</h3>
            <p className="text-muted-foreground">Zero-click workflows powered by September 2025 AI</p>
          </div>

          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoMode}
                onChange={(e) => setAutoMode(e.target.checked)}
                className="rounded border-border"
              />
              <span className="text-foreground">Auto-start recommended workflows</span>
            </label>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {templates.map((template) => {
            const Icon = template.icon;
            const isRunning = workflows.some(w => w.input_data?.template_id === template.id && (w.status === 'initiated' || w.status === 'approved'));

            return (
              <GlassCard key={template.id} className="p-6 hover:bg-muted/5 transition-colors">
                <div className="flex items-start gap-4">
                  <div className="p-3 rounded-lg bg-primary/10">
                    <Icon className="w-6 h-6 text-primary" />
                  </div>

                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h4 className="font-semibold text-foreground">{template.name}</h4>
                      {template.autonomous && (
                        <span className="px-2 py-1 bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 rounded text-xs font-medium">
                          Autonomous
                        </span>
                      )}
                      {isRunning && (
                        <span className="px-2 py-1 bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400 rounded text-xs font-medium">
                          Running
                        </span>
                      )}
                    </div>

                    <p className="text-sm text-muted-foreground mb-4">{template.description}</p>

                    <div className="space-y-2 mb-4">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Clock className="w-3 h-3" />
                        <span>Est. time: {template.estimatedTime}</span>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Zap className="w-3 h-3" />
                        <span>{template.requirements.length} requirements</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {!isRunning ? (
                        <button
                          onClick={() => startWorkflow(template.id)}
                          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
                        >
                          Start Workflow
                        </button>
                      ) : (
                        <span className="px-4 py-2 bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 rounded-lg text-sm font-medium">
                          Currently Running
                        </span>
                      )}

                      <button className="p-2 rounded-lg hover:bg-muted/20 transition-colors">
                        <Settings className="w-4 h-4 text-muted-foreground" />
                      </button>
                    </div>
                  </div>
                </div>
              </GlassCard>
            );
          })}
        </div>
      </div>
    );
  };

  const renderAnalytics = () => {
    return (
      <div className="space-y-6">
        <h3 className="text-lg font-semibold text-foreground">Workflow Analytics</h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <GlassCard className="p-6 text-center">
            <div className="w-12 h-12 bg-green-100 dark:bg-green-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
              <CheckCircle className="w-6 h-6 text-green-600 dark:text-green-400" />
            </div>
            <div className="text-2xl font-bold text-foreground mb-2">
              {workflows.length}
            </div>
            <div className="text-sm text-muted-foreground">Total Executions</div>
          </GlassCard>

          <GlassCard className="p-6 text-center">
            <div className="w-12 h-12 bg-blue-100 dark:bg-blue-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
              <TrendingUp className="w-6 h-6 text-blue-600 dark:text-blue-400" />
            </div>
            <div className="text-2xl font-bold text-foreground mb-2">
              {workflows.filter(w => w.result).length}
            </div>
            <div className="text-sm text-muted-foreground">Results Generated</div>
          </GlassCard>

          <GlassCard className="p-6 text-center">
            <div className="w-12 h-12 bg-slate-100 dark:bg-slate-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
              <Bot className="w-6 h-6 text-primary dark:text-primary" />
            </div>
            <div className="text-2xl font-bold text-foreground mb-2">
              {workflows.filter(w => w.status === 'initiated' || w.status === 'approved').length}
            </div>
            <div className="text-sm text-muted-foreground">Active Workflows</div>
          </GlassCard>
        </div>

        <GlassCard className="p-6">
          <h4 className="font-semibold text-foreground mb-4">Autonomous Operations Impact</h4>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Time Saved (Human Hours)</span>
              <span className="font-semibold text-foreground">247 hours</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Cost Reduction</span>
              <span className="font-semibold text-green-600">$12,350</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Lead Quality Improvement</span>
              <span className="font-semibold text-blue-600">+34%</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Response Rate</span>
              <span className="font-semibold text-accent">23.7%</span>
            </div>
          </div>
        </GlassCard>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Autonomous AI Workflows</h1>
          <p className="text-muted-foreground">Zero-click automation powered by September 2025 AI</p>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">Auto Mode:</span>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={autoMode}
              onChange={(e) => setAutoMode(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"></div>
          </label>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex items-center gap-1 p-1 bg-muted/20 rounded-lg">
        <button
          onClick={() => setActiveTab('running')}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors',
            activeTab === 'running'
              ? 'bg-background/80 backdrop-blur-sm text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/10'
          )}
        >
          <Activity className="w-4 h-4" />
          Running ({workflows.filter(w => w.status === 'initiated' || w.status === 'approved').length})
        </button>

        <button
          onClick={() => setActiveTab('templates')}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors',
            activeTab === 'templates'
              ? 'bg-background/80 backdrop-blur-sm text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/10'
          )}
        >
          <Bot className="w-4 h-4" />
          Templates ({templates.length})
        </button>

        <button
          onClick={() => setActiveTab('analytics')}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors',
            activeTab === 'analytics'
              ? 'bg-background/80 backdrop-blur-sm text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/10'
          )}
        >
          <TrendingUp className="w-4 h-4" />
          Analytics
        </button>
      </div>

      {/* Tab Content */}
      <div className="min-h-[400px]">
        {activeTab === 'running' && renderRunningWorkflows()}
        {activeTab === 'templates' && renderTemplates()}
        {activeTab === 'analytics' && renderAnalytics()}
      </div>
    </div>
  );
};

export default AutonomousWorkflows;
