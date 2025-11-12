// Loading Skeleton Components - Glassmorphic Design
// September 2025 AI Integration

import React from 'react';
import { cn } from '../../lib/utils';
import { useReducedMotion } from '../../lib/accessibility';

interface SkeletonProps {
  className?: string;
  animate?: boolean;
  style?: React.CSSProperties;
  'aria-label'?: string;
}

export const Skeleton: React.FC<SkeletonProps> = ({
  className,
  animate = true,
  style,
  'aria-label': ariaLabel
}) => {
  const prefersReducedMotion = useReducedMotion();
  const shouldAnimate = animate && !prefersReducedMotion;

  return (
    <div
      className={cn(
        'bg-muted/30 rounded-lg',
        shouldAnimate && 'animate-pulse',
        className
      )}
      style={style}
      role="presentation"
      aria-label={ariaLabel ?? 'Loading content'}
      aria-hidden="true"
    />
  );
};

// Card Skeleton for approval cards, dashboard cards etc.
export const CardSkeleton: React.FC = () => {
  return (
    <div
      className="bg-background/80 backdrop-blur-xl border border-border/20 rounded-xl p-4 space-y-4"
      role="status"
      aria-label="Loading card content"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Skeleton className="w-10 h-10 rounded-full" aria-label="Loading avatar" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-32" aria-label="Loading title" />
            <Skeleton className="h-3 w-24" aria-label="Loading subtitle" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Skeleton className="h-6 w-16 rounded-full" aria-label="Loading status badge" />
          <Skeleton className="h-6 w-20 rounded-full" aria-label="Loading action badge" />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Skeleton className="h-3 w-20" aria-label="Loading metadata" />
          <Skeleton className="h-3 w-16" aria-label="Loading metadata" />
          <Skeleton className="h-3 w-12" aria-label="Loading metadata" />
        </div>
        <Skeleton className="w-4 h-4" aria-label="Loading icon" />
      </div>
    </div>
  );
};

// Chart Skeleton for analytics
export const ChartSkeleton: React.FC = () => {
  return (
    <div className="bg-background/80 backdrop-blur-xl border border-border/20 rounded-xl p-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-4 w-20" />
        </div>
        <div className="h-64 bg-muted/20 rounded-lg flex items-end justify-center gap-2 p-4">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton
              key={i}
              className="w-8 rounded-sm"
              style={{ height: `${Math.random() * 80 + 20}%` }}
            />
          ))}
        </div>
        <div className="flex items-center justify-center gap-4">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-18" />
        </div>
      </div>
    </div>
  );
};

// Stats Card Skeleton for metrics
export const StatsCardSkeleton: React.FC = () => {
  return (
    <div className="bg-background/80 backdrop-blur-xl border border-border/20 rounded-xl p-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Skeleton className="w-8 h-8 rounded-lg" />
          <Skeleton className="h-4 w-12" />
        </div>
        <div className="space-y-2">
          <Skeleton className="h-8 w-20" />
          <Skeleton className="h-4 w-24" />
        </div>
        <div className="flex items-center gap-2">
          <Skeleton className="h-3 w-3" />
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
    </div>
  );
};

// Table Row Skeleton
export const TableRowSkeleton: React.FC = () => {
  return (
    <div className="flex items-center gap-4 p-4 border-b border-border/20">
      <Skeleton className="w-8 h-8 rounded-full" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-full max-w-md" />
        <Skeleton className="h-3 w-3/4" />
      </div>
      <Skeleton className="h-6 w-20 rounded-full" />
      <Skeleton className="w-6 h-6" />
    </div>
  );
};

// Navigation Skeleton for sidebar
export const NavSkeleton: React.FC = () => {
  return (
    <div className="space-y-2">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 p-3 rounded-lg">
          <Skeleton className="w-5 h-5 rounded" />
          <div className="flex-1 space-y-1">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-20" />
          </div>
        </div>
      ))}
    </div>
  );
};

// Text Lines Skeleton
interface TextSkeletonProps {
  lines?: number;
  className?: string;
}

export const TextSkeleton: React.FC<TextSkeletonProps> = ({
  lines = 3,
  className
}) => {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn(
            'h-4',
            i === lines - 1 ? 'w-3/4' : 'w-full'
          )}
        />
      ))}
    </div>
  );
};

// Form Skeleton
export const FormSkeleton: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-10 w-full rounded-lg" />
      </div>
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-10 w-full rounded-lg" />
      </div>
      <div className="space-y-2">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
      <div className="flex justify-end gap-3">
        <Skeleton className="h-10 w-20 rounded-lg" />
        <Skeleton className="h-10 w-24 rounded-lg" />
      </div>
    </div>
  );
};

// Dashboard Overview Skeleton
export const DashboardSkeleton: React.FC = () => {
  return (
    <div
      className="space-y-6"
      role="status"
      aria-label="Loading dashboard content"
    >
      {/* Live region for screen reader announcements */}
      <div className="sr-only" aria-live="polite" role="status">
        Loading dashboard overview. Please wait while we fetch your analytics data.
      </div>

      {/* Header Stats */}
      <section aria-label="Loading key metrics">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <StatsCardSkeleton key={i} />
          ))}
        </div>
      </section>

      {/* Charts Section */}
      <section aria-label="Loading analytics charts">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartSkeleton />
          <ChartSkeleton />
        </div>
      </section>

      {/* Recent Activity */}
      <section aria-label="Loading recent activity">
        <div className="bg-background/80 backdrop-blur-xl border border-border/20 rounded-xl p-6">
          <div className="space-y-4">
            <Skeleton className="h-6 w-32" aria-label="Loading section title" />
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <TableRowSkeleton key={i} />
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

// Approval Queue Skeleton
export const ApprovalQueueSkeleton: React.FC = () => {
  return (
    <div className="space-y-4">
      {/* Filter Tabs */}
      <div className="flex gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-20 rounded-lg" />
        ))}
      </div>

      {/* Approval Cards */}
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
};
