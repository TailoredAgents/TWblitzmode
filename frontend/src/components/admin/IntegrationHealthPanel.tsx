'use client';

import React from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import GlassCard from '../ui/GlassCard';

interface IntegrationEntry {
  provider: string;
  status: string;
  failures: number;
  lastChecked: string | null;
  configured: boolean;
}

interface IntegrationHealthPanelProps {
  entries: IntegrationEntry[];
  loading: boolean;
  onRefresh: () => void | Promise<void>;
  formatDate: (value?: string | null) => string;
}

export function IntegrationHealthPanel({ entries, loading, onRefresh, formatDate }: IntegrationHealthPanelProps) {
  return (
    <GlassCard className="space-y-4 p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Integration validation</h2>
          <p className="text-sm text-muted-foreground">
            Track health checks for linked services. Use refresh after adjusting credentials or connection policies.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void onRefresh()}
          className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 disabled:opacity-60"
          disabled={loading}
          data-testid="admin-integrations-refresh"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {loading ? 'Checking…' : 'Refresh'}
        </button>
      </div>

      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Integration telemetry will appear after the first validation run. Click refresh to initiate one now.
        </p>
      ) : (
        <div className="space-y-3">
          {entries.map(({ provider, status, failures, lastChecked, configured }) => {
            const normalized = status.toLowerCase();
            let statusClass = 'bg-amber-500/20 text-amber-600';
            if (['healthy', 'success', 'ok', 'available', 'connected'].some((token) => normalized.includes(token))) {
              statusClass = 'bg-emerald-500/20 text-emerald-600';
            }
            if (['error', 'fail', 'down', 'blocked'].some((token) => normalized.includes(token))) {
              statusClass = 'bg-rose-500/20 text-rose-600';
            }

            return (
              <div
                key={provider}
                data-testid={`admin-integration-${provider}`}
                className="rounded-lg border border-border/40 bg-white/80 p-4 shadow-sm transition hover:shadow-md dark:bg-slate-900/40"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-foreground capitalize">{provider.replace(/[_-]/g, ' ')}</span>
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusClass}`}>
                    {status}
                  </span>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-muted-foreground md:grid-cols-3">
                  <div>
                    <span className="font-medium text-foreground">Configured:</span>{' '}
                    <span className={configured ? 'font-semibold text-emerald-600' : 'font-semibold text-rose-600'}>
                      {configured ? 'Yes' : 'No'}
                    </span>
                  </div>
                  <div>
                    <span className="font-medium text-foreground">Failures (24h):</span>{' '}
                    <span className="text-foreground">{failures}</span>
                  </div>
                  <div>
                    <span className="font-medium text-foreground">Last checked:</span>{' '}
                    <span className="text-foreground">{lastChecked ? formatDate(lastChecked) : '—'}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
