import type { Meta, StoryObj } from '@storybook/react';
import GlassCard from './GlassCard';

const meta: Meta<typeof GlassCard> = {
  title: 'UI/GlassCard',
  component: GlassCard,
  parameters: {
    layout: 'centered',
  },
  args: {
    variant: 'default',
    blur: 'lg',
    padding: 'lg',
    children: (
      <div className="space-y-2">
        <h3 className="text-lg font-semibold text-foreground">Tallwave</h3>
        <p className="text-sm text-muted-foreground">
          Enterprise-grade warm introduction orchestration with secure LinkedIn session management.
        </p>
      </div>
    ),
  },
};

export default meta;

type Story = StoryObj<typeof GlassCard>;

export const Default: Story = {};

export const Interactive: Story = {
  args: {
    variant: 'interactive',
  },
};

export const Strong: Story = {
  args: {
    variant: 'strong',
    padding: 'xl',
  },
};
