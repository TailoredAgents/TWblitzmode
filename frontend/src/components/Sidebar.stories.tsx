import type { Meta, StoryObj } from '@storybook/react';
import Sidebar from './Sidebar';
import type { Organization, User } from '../types';
import { fn } from '@storybook/test';

const sampleOrg: Organization = {
  id: 501,
  name: 'Tailored Agents HQ',
  status: 'active',
  subscription_tier: 'enterprise',
};

const sampleUser: User = {
  id: 101,
  email: 'ops@tallwave.com',
  name: 'Jordan Carter',
  organization: {
    ...sampleOrg,
  },
  role: 'admin',
  tenant_id: 501,
  accepted_terms_at: new Date().toISOString(),
};

const meta: Meta<typeof Sidebar> = {
  title: 'Navigation/Sidebar',
  component: Sidebar,
  parameters: {
    layout: 'fullscreen',
  },
  args: {
    activeView: 'dashboard',
    onViewChange: fn(),
    user: sampleUser,
    pendingApprovals: 3,
    sidebarOpen: true,
    setSidebarOpen: fn(),
  },
};

export default meta;

type Story = StoryObj<typeof Sidebar>;

export const Default: Story = {};

export const Compact: Story = {
  args: {
    sidebarOpen: false,
    activeView: 'approvals',
  },
  parameters: {
    viewport: {
      defaultViewport: 'mobile1',
    },
  },
};
