import type { Meta, StoryObj } from '@storybook/react';
import Toast from './Toast';
import { fn } from '@storybook/test';

const meta: Meta<typeof Toast> = {
  title: 'UI/Toast',
  component: Toast,
  parameters: {
    layout: 'centered',
  },
  args: {
    id: 'storybook-toast',
    title: 'Saved successfully',
    description: 'Your changes have been synchronized across tenants.',
    variant: 'success',
    duration: 0,
    dismissible: true,
  },
  argTypes: {
    onDismiss: { action: 'dismissed' },
  },
};

export default meta;

type Story = StoryObj<typeof Toast>;

export const Success: Story = {};

export const Error: Story = {
  args: {
    title: 'Something went wrong',
    description: 'Please retry the operation or contact Tailored Agents support.',
    variant: 'error',
  },
};

export const WithAction: Story = {
  args: {
    title: 'Approval needed',
    description: 'A workflow pause requires human review.',
    variant: 'warning',
    action: {
      label: 'Open approvals',
      onClick: fn(),
    },
  },
};
