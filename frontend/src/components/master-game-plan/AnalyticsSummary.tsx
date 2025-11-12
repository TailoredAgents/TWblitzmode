import React, { useMemo } from 'react';
import { TrendingUp, Users, Zap, Clock } from 'lucide-react';
import GlassCard from '../ui/GlassCard';
import type { AnalyticsOverview, CorporateWorkflowMetrics } from '../../types';

interface AnalyticsSummaryProps {
  analytics: AnalyticsOverview | null;
  metrics: CorporateWorkflowMetrics | null;
}

const AnalyticsSummary: React.FC<AnalyticsSummaryProps> = ({ analytics, metrics }) => {
  const cards = useMemo(
    () => [
      {
        label: 'Prospects engaged',
        value: analytics?.prospects?.total ?? 0,
        icon: Users,
      },
      {
        label: 'Mutual connectors identified',
        value: analytics?.prospects?.with_connectors ?? 0,
        icon: TrendingUp,
      },
      {
        label: 'Active workflows',
        value: metrics?.running_workflows ?? metrics?.workflows_running ?? 0,
        icon: Zap,
      },
      {
        label: 'Avg approval time (min)',
        value: metrics?.average_approval_time_minutes
          ? metrics.average_approval_time_minutes.toFixed(1)
          : '—',
        icon: Clock,
      },
    ],
    [analytics, metrics],
  );

  return (
    <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {cards.map(({ label, value, icon: Icon }) => (
        <GlassCard key={label} className="flex items-center justify-between p-4 shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
            <p className="mt-2 text-2xl font-bold text-foreground">{value}</p>
          </div>
          <div className="rounded-full bg-primary/10 p-3 text-primary">
            <Icon className="h-5 w-5" />
          </div>
        </GlassCard>
      ))}
    </section>
  );
};

export default AnalyticsSummary;
