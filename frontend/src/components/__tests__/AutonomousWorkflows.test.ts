import { deriveWorkflowMetrics } from '../AutonomousWorkflows';
import type { AIWorkflow } from '../../types';

const baseWorkflow: AIWorkflow = {
  workflow_id: 'wf-123',
  type: 'prospect_analysis',
  status: 'completed',
  organization_id: 'org-1',
  user_id: 'user-1',
  input_data: {},
  result: {},
  pending_approvals: [],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe('deriveWorkflowMetrics', () => {
  it('extracts numeric metrics from result payloads', () => {
    const workflow: AIWorkflow = {
      ...baseWorkflow,
      result: {
        executions: 4,
        success_rate: 0.62,
        results_generated: 12,
        cost_savings: '$1,250',
      },
    };

    const metrics = deriveWorkflowMetrics(workflow);
    expect(metrics.executions).toBe(4);
    expect(metrics.successRate).toBe(62);
    expect(metrics.resultsGenerated).toBe(12);
    expect(metrics.costSavings).toBe(1250);
  });

  it('derives success rate from completed and total workflow counts', () => {
    const workflow: AIWorkflow = {
      ...baseWorkflow,
      result: {
        completed_workflows: 8,
        total_workflows: 10,
      },
    };

    const metrics = deriveWorkflowMetrics(workflow);
    expect(metrics.successRate).toBe(80);
  });
});
