'use client';

import React from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import GlassCard from '../ui/GlassCard';
import type { OnboardingProgress } from '../../types';

interface OnboardingProgressPanelProps {
  progress: OnboardingProgress | null;
  onSendNudge: () => void | Promise<void>;
  nudgeLoading: boolean;
  formatDate: (value?: string | null) => string;
}

export function OnboardingProgressPanel({ progress, onSendNudge, nudgeLoading, formatDate }: OnboardingProgressPanelProps) {
  const stalledMembers = progress?.stalled_members ?? [];
  const pendingTermsCount = progress?.pending_terms ?? 0;
  const cookiePendingCount = progress?.cookie_pending ?? 0;
  const neverLoggedInCount = progress?.never_logged_in ?? 0;
  const lastUpdatedLabel = progress?.generated_at ? formatDate(progress.generated_at) : '—';
  const autoNudgeInfo = progress?.auto_nudge ?? null;
  const lastAutoNudgeLabel = autoNudgeInfo?.last_sent_at ? formatDate(autoNudgeInfo.last_sent_at) : 'Not yet sent automatically';
  const autoNudgeCooldownLabel = autoNudgeInfo
    ? autoNudgeInfo.cooldown_seconds >= 3600
      ? `${Math.round(autoNudgeInfo.cooldown_seconds / 3600)}h`
      : `${Math.max(1, Math.round(autoNudgeInfo.cooldown_seconds / 60))}m`
    : null;

  return (
    <GlassCard className="space-y-4 p-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Onboarding Progress</h2>
          <p className="text-xs text-muted-foreground">
            Track terms acceptance, cookie uploads, and first logins for your team. Last updated {lastUpdatedLabel}.
          </p>
          {autoNudgeInfo ? (
            <p className="text-xs text-muted-foreground">
              Automatic reminders: {autoNudgeInfo.enabled ? lastAutoNudgeLabel : 'Disabled'}
              {autoNudgeInfo.enabled && autoNudgeCooldownLabel ? ` • Cooldown ${autoNudgeCooldownLabel}` : ''}
            </p>
          ) : null}
          {autoNudgeInfo?.errors && autoNudgeInfo.errors.length > 0 ? (
            <p className="text-xs text-amber-500">Recent delivery issues: {autoNudgeInfo.errors[0]}</p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void onSendNudge()}
          disabled={nudgeLoading || stalledMembers.length === 0}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {nudgeLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertCircle className="h-4 w-4" />}
          {stalledMembers.length === 0 ? 'All Members On Track' : 'Send Reminder'}
        </button>
      </div>

      <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-lg border border-border/30 bg-muted/20 px-3 py-2">
          <p className="text-xs text-muted-foreground">Pending Terms</p>
          <p className="text-lg font-semibold text-primary">{pendingTermsCount}</p>
        </div>
        <div className="rounded-lg border border-border/30 bg-muted/20 px-3 py-2">
          <p className="text-xs text-muted-foreground">Cookie Updates Needed</p>
          <p className="text-lg font-semibold text-primary">{cookiePendingCount}</p>
        </div>
        <div className="rounded-lg border border-border/30 bg-muted/20 px-3 py-2">
          <p className="text-xs text-muted-foreground">Never Logged In</p>
          <p className="text-lg font-semibold text-primary">{neverLoggedInCount}</p>
        </div>
      </div>

      {stalledMembers.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Members needing attention</p>
          <div className="space-y-2">
            {stalledMembers.map((member) => (
              <div
                key={member.id}
                className="flex flex-col gap-1 rounded-lg border border-border/20 bg-muted/20 px-3 py-2 md:flex-row md:items-center md:justify-between"
              >
                <div>
                  <p className="text-sm font-medium text-foreground">{member.name ?? member.email ?? 'Team member'}</p>
                  <p className="text-xs text-muted-foreground">{member.email ?? 'No email on file'}</p>
                </div>
                <div className="text-xs text-muted-foreground md:text-right">
                  <span className="font-medium text-foreground">Needs:</span> {member.reasons.join(', ')}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">All members have completed onboarding requirements.</p>
      )}
    </GlassCard>
  );
}
