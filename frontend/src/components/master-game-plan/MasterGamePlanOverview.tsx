import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useToastActions } from '../ui/ToastContainer';
import { apiService } from '../../services/api';
import type {
  AnalyticsOverview,
  CorporateWorkflowMetrics,
  CorporateWorkflowRun,
  User,
} from '../../types';
import { stringifyId } from '../../lib/utils';
import AnalyticsSummary from './AnalyticsSummary';
import WorkflowsTable from './WorkflowsTable';
import UploadPanel from './UploadPanel';
import GlassCard from '../ui/GlassCard';

interface MasterGamePlanOverviewProps {
  organizationId: string | number;
  tenantId?: string | number;
  userRole?: User['role'];
}

const MasterGamePlanOverview: React.FC<MasterGamePlanOverviewProps> = ({
  organizationId,
  tenantId,
}) => {
  const { success, error } = useToastActions();
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [metrics, setMetrics] = useState<CorporateWorkflowMetrics | null>(null);
  const [workflows, setWorkflows] = useState<CorporateWorkflowRun[]>([]);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);
  const [metricsLoading, setMetricsLoading] = useState(true);
  const [workflowsLoading, setWorkflowsLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  const organizationKey = useMemo(
    () => stringifyId(organizationId),
    [organizationId],
  );
  const tenantKey = useMemo(
    () => stringifyId(tenantId ?? organizationId),
    [tenantId, organizationId],
  );

  const effectiveTenant = tenantKey ?? organizationKey;

  const loadAnalytics = useCallback(async () => {
    if (!organizationKey) {
      setAnalytics(null);
      setAnalyticsLoading(false);
      return;
    }

    try {
      setAnalyticsLoading(true);
      const response = await apiService.getAnalyticsOverview(organizationKey);
      setAnalytics(response.data ?? null);
    } catch (err) {
      console.error('Failed to load analytics overview:', err);
      error('Unable to load analytics overview');
      setAnalytics(null);
    } finally {
      setAnalyticsLoading(false);
    }
  }, [organizationKey, error]);

  const loadMetrics = useCallback(async () => {
    if (!effectiveTenant) {
      setMetrics(null);
      setMetricsLoading(false);
      return;
    }

    try {
      setMetricsLoading(true);
      const response = await apiService.getCorporateWorkflowMetrics(effectiveTenant);
      setMetrics(response.data ?? null);
    } catch (err) {
      console.error('Failed to load workflow metrics:', err);
      error('Unable to load workflow metrics');
      setMetrics(null);
    } finally {
      setMetricsLoading(false);
    }
  }, [effectiveTenant, error]);

  const loadWorkflows = useCallback(async () => {
    if (!effectiveTenant) {
      setWorkflows([]);
      setWorkflowsLoading(false);
      return;
    }
    try {
      setWorkflowsLoading(true);
      const [corporateRes, activeRes] = await Promise.all([
        apiService
          .getCorporateWorkflows(effectiveTenant)
          .catch(() => ({ data: { workflows: [] as CorporateWorkflowRun[] } })),
        apiService
          .getActiveWorkflows(effectiveTenant)
          .catch(() => ({ data: { workflows: [] as CorporateWorkflowRun[] } })),
      ]);

      const combined = [
        ...(corporateRes.data?.workflows ?? []),
        ...(activeRes.data?.workflows ?? []),
      ];

      const uniqueMap = new Map<string, CorporateWorkflowRun>();
      combined.forEach((workflow) => {
        if (workflow?.workflow_id) {
          uniqueMap.set(workflow.workflow_id, workflow);
        }
      });

      setWorkflows(Array.from(uniqueMap.values()));
    } catch (err) {
      console.error('Failed to load workflows:', err);
      error('Unable to load workflows list');
      setWorkflows([]);
    } finally {
      setWorkflowsLoading(false);
    }
  }, [effectiveTenant, error]);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  useEffect(() => {
    loadMetrics();
  }, [loadMetrics]);

  useEffect(() => {
    loadWorkflows();
  }, [loadWorkflows]);

  const handleUploadFile = useCallback(
    async (file: File, priority: 'low' | 'normal' | 'high') => {
      if (!effectiveTenant) {
        error('Tenant context missing. Upload unavailable.');
        return;
      }
      try {
        setUploading(true);
        await apiService.startCorporateWorkflow(effectiveTenant, file, { priority });
        success('Workflow queued successfully');
        await loadWorkflows();
      } catch (err) {
        console.error('Failed to upload workflow file:', err);
        error('Unable to upload workflow file');
      } finally {
        setUploading(false);
      }
    },
    [effectiveTenant, error, loadWorkflows, success],
  );

  const handleManualList = useCallback(
    async (companyList: string, priority: 'low' | 'normal' | 'high') => {
      if (!effectiveTenant) {
        error('Tenant context missing. Upload unavailable.');
        return;
      }
      try {
        setUploading(true);
        await apiService.startCorporateWorkflow(effectiveTenant, undefined, {
          priority,
          companyList,
        });
        success('Workflow queued successfully');
        await loadWorkflows();
      } catch (err) {
        console.error('Failed to queue manual workflow:', err);
        error('Unable to queue workflow');
      } finally {
        setUploading(false);
      }
    },
    [effectiveTenant, error, loadWorkflows, success],
  );

  if (!organizationKey) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Waiting for organization context…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {(analyticsLoading || metricsLoading) && (
        <GlassCard className="p-6 text-sm text-muted-foreground">Loading analytics…</GlassCard>
      )}

      {!analyticsLoading && !metricsLoading && (
        <AnalyticsSummary analytics={analytics} metrics={metrics} />
      )}

      <UploadPanel
        isUploading={uploading}
        onUploadFile={handleUploadFile}
        onSubmitManualList={handleManualList}
      />

      <WorkflowsTable
        workflows={workflows}
        loading={workflowsLoading}
        onRefresh={loadWorkflows}
      />
    </div>
  );
};

export default MasterGamePlanOverview;
