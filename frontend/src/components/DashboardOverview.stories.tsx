import type { Meta, StoryObj } from '@storybook/react';
import React from 'react';
import DashboardOverview from './DashboardOverview';
import { apiService } from '../services/api';
import webSocketService from '../services/websocket';
import type { AnalyticsOverview } from '../types';

const sampleAnalytics: AnalyticsOverview = {
  prospects: {
    total: 128,
    by_status: {
      pending_lookup: 24,
      lookup_complete: 36,
      mutuals_found: 18,
      enriched: 28,
      scheduled: 12,
      contacted: 10,
    },
    this_week: 22,
    completion_rate: 0.64,
    activity_trend: [
      { name: 'Mon', contacts: 18, responses: 8, meetings: 3 },
      { name: 'Tue', contacts: 20, responses: 11, meetings: 4 },
      { name: 'Wed', contacts: 24, responses: 14, meetings: 5 },
      { name: 'Thu', contacts: 21, responses: 12, meetings: 4 },
      { name: 'Fri', contacts: 16, responses: 9, meetings: 3 },
      { name: 'Sat', contacts: 8, responses: 4, meetings: 1 },
      { name: 'Sun', contacts: 5, responses: 2, meetings: 0 },
    ],
    response_trend: [
      { month: 'Jan', rate: 28 },
      { month: 'Feb', rate: 32 },
      { month: 'Mar', rate: 35 },
      { month: 'Apr', rate: 39 },
      { month: 'May', rate: 41 },
      { month: 'Jun', rate: 44 },
    ],
  },
  connectors: {
    total: 412,
    with_emails: 268,
    avg_score: 0.82,
  },
  workflows: {
    total: 18,
    pending_approval: 2,
    completed_this_week: 11,
    success_rate: 0.74,
    distribution: [
      { name: 'Email Automation', value: 48 },
      { name: 'Lead Scoring', value: 24 },
      { name: 'Follow-up Scheduling', value: 16 },
      { name: 'Data Enrichment', value: 12 },
    ],
  },
  quotas: {
    emails_sent_this_week: 184,
    weekly_limit: 500,
    utilization: 0.37,
  },
  integrations: {
    apify: 'connected',
    cufinder: 'connected',
    email_provider: 'connected',
  },
  metadata: {
    last_updated: new Date().toISOString(),
    tenant_id: 'demo-tenant',
    user_id: 101,
  },
};

const DashboardDecorator: React.FC<React.PropsWithChildren> = ({ children }) => {
  React.useEffect(() => {
    const originalAnalytics = apiService.getAnalyticsOverview;
    const originalConnect = webSocketService.connect;
    const originalJoinOrg = webSocketService.joinOrganizationRoom;
    const originalJoinApproval = webSocketService.joinApprovalRoom;
    const originalOn = webSocketService.on;
    const originalOff = webSocketService.off;

    apiService.getAnalyticsOverview = async () => ({
      status: 200,
      data: sampleAnalytics,
    });
    webSocketService.connect = () => undefined;
    webSocketService.joinOrganizationRoom = () => undefined;
    webSocketService.joinApprovalRoom = () => undefined;
    webSocketService.on = () => undefined;
    webSocketService.off = () => undefined;

    return () => {
      apiService.getAnalyticsOverview = originalAnalytics;
      webSocketService.connect = originalConnect;
      webSocketService.joinOrganizationRoom = originalJoinOrg;
      webSocketService.joinApprovalRoom = originalJoinApproval;
      webSocketService.on = originalOn;
      webSocketService.off = originalOff;
    };
  }, []);

  return <>{children}</>;
};

const meta: Meta<typeof DashboardOverview> = {
  title: 'Dashboard/Overview',
  component: DashboardOverview,
  decorators: [
    (Story) => (
      <DashboardDecorator>
        <Story />
      </DashboardDecorator>
    ),
  ],
  parameters: {
    layout: 'fullscreen',
  },
  args: {
    organizationId: 501,
    userId: 101,
  },
};

export default meta;

type Story = StoryObj<typeof DashboardOverview>;

export const Default: Story = {};
