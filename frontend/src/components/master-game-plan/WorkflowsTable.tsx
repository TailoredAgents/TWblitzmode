import React from 'react';
import GlassCard from '../ui/GlassCard';
import type { CorporateWorkflowRun } from '../../types';
import { cn } from '../../lib/utils';

interface WorkflowsTableProps {
  workflows: CorporateWorkflowRun[];
  loading: boolean;
  onRefresh: () => void;
}

const statusBadgeStyles: Record<string, string> = {
  approved: 'bg-green-100 text-green-700 dark:bg-green-500/10 dark:text-green-300',
  completed: 'bg-green-100 text-green-700 dark:bg-green-500/10 dark:text-green-300',
  pending_approval: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/10 dark:text-yellow-300',
  failed: 'bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300',
  rejected: 'bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300',
  initiated: 'bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300',
};

const WorkflowsTable: React.FC<WorkflowsTableProps> = ({ workflows, loading, onRefresh }) => {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Workflow pipeline</h2>
        <button
          type="button"
          onClick={onRefresh}
          className="text-sm text-primary hover:text-primary/80"
        >
          Refresh
        </button>
      </div>

      <GlassCard className="overflow-hidden">
        <table className="min-w-full divide-y divide-border/40 text-sm">
          <thead className="bg-muted/20 text-muted-foreground">
            <tr>
              <th scope="col" className="px-4 py-3 text-left font-medium">Workflow</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">Status</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">Prospects</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">Connectors</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">Updated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/20">
            {loading && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  Loading workflows…
                </td>
              </tr>
            )}

            {!loading && workflows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  No workflows have been scheduled yet.
                </td>
              </tr>
            )}

            {!loading &&
              workflows.map((workflow) => (
                <tr key={workflow.workflow_id} className="hover:bg-muted/10">
                  <td className="px-4 py-3">
                    <div className="font-medium text-foreground">{workflow.workflow_id}</div>
                    <div className="text-xs text-muted-foreground">{workflow.type}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full px-2 py-1 text-xs font-medium',
                        statusBadgeStyles[workflow.status] ??
                          'bg-slate-100 text-slate-700 dark:bg-slate-500/10 dark:text-slate-300',
                      )}
                    >
                      {workflow.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3">{workflow.prospects_processed ?? 0}</td>
                  <td className="px-4 py-3">{workflow.connectors_found ?? 0}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {workflow.updated_at
                      ? new Date(workflow.updated_at).toLocaleString()
                      : '—'}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </GlassCard>
    </section>
  );
};

export default WorkflowsTable;
