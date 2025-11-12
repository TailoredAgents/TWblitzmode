import React from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, ShieldCheck, Users, Wallet } from 'lucide-react';
import GlassCard from '../../../components/ui/GlassCard';
import { OnboardingProgressPanel } from '../../../components/admin/OnboardingProgressPanel';
import type {
  OnboardingProgress,
  OrganizationProfile,
  SeatSummary,
  TierDetails,
} from '../../../types';

const MAX_LIST_ITEMS = 5;
const MAX_GUARDRAIL_ITEMS = 4;

interface SeatUtilizationCardProps {
  profile: OrganizationProfile;
  seatUsage: SeatSummary | null | undefined;
  statusBadgeClasses: Record<string, string>;
}

export function SeatUtilizationCard({ profile, seatUsage, statusBadgeClasses }: SeatUtilizationCardProps) {
  return (
    <GlassCard className="p-6 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">Seat Utilization</h2>
        <Users className="w-4 h-4 text-primary" />
      </div>
      <p className="text-3xl font-semibold text-primary">
        {seatUsage?.active ?? 0}
        <span className="text-base text-muted-foreground">
          {' '}
          / {seatUsage?.limit ?? profile.max_team_members}
        </span>
      </p>
      <div className="text-xs text-muted-foreground space-y-1">
        <p>Unused keys: {seatUsage?.unused_keys ?? 0}</p>
        <p>
          Status:{' '}
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs uppercase tracking-wide ${
              statusBadgeClasses[profile.status] ?? 'bg-slate-500/20 text-slate-600'
            }`}
          >
            {profile.status}
          </span>
        </p>
      </div>
    </GlassCard>
  );
}

interface CookieStatusCardProps {
  hasCookieAccess: boolean;
  validCookieCount: number;
  totalTeamMembers: number;
  onNavigateToBilling: () => void;
}

export function CookieStatusCard({ hasCookieAccess, validCookieCount, totalTeamMembers, onNavigateToBilling }: CookieStatusCardProps) {
  if (hasCookieAccess) {
    return (
      <GlassCard className="p-6 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">Cookie Compliance</h2>
          <ShieldCheck className="w-4 h-4 text-primary" />
        </div>
        <p className="text-3xl font-semibold text-primary">
          {validCookieCount}
          <span className="text-base text-muted-foreground"> / {totalTeamMembers}</span>
        </p>
        <p className="text-xs text-muted-foreground">
          Valid cookie jars across your team. Encourage members with pending or invalid statuses to upload fresh LinkedIn cookies.
        </p>
      </GlassCard>
    );
  }

  return (
    <GlassCard className="p-6 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">Cookie Vault Guardrails</h2>
        <ShieldCheck className="w-4 h-4 text-muted-foreground" />
      </div>
      <p className="text-sm text-muted-foreground">
        Secure cookie storage activates on Growth and Enterprise plans. Upgrade to unlock automated LinkedIn compliance workflows.
      </p>
      <button
        type="button"
        onClick={onNavigateToBilling}
        className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:text-primary/80 transition-colors"
      >
        Review plan options
        <ArrowRight className="w-4 h-4" />
      </button>
    </GlassCard>
  );
}

interface PlanBillingCardProps {
  profile: OrganizationProfile;
  billingEnabled: boolean;
}

export function PlanBillingCard({ profile, billingEnabled }: PlanBillingCardProps) {
  const subscriptionStatus = profile.account_overview?.subscription_status ?? 'active';
  const seatPolicy = profile.account_overview?.seat_policy ?? null;
  const seatPolicyLabel =
    (seatPolicy?.description ?? seatPolicy?.type ?? 'unlimited').toString();

  return (
    <GlassCard className="p-6 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">Plan & Billing</h2>
        <Wallet className="w-4 h-4 text-primary" />
      </div>
      <p className="text-lg font-semibold text-primary capitalize">{profile.subscription_tier} Plan</p>
      {billingEnabled ? (
        <>
          <p className="text-xs text-muted-foreground">
            Seats provisioned: {profile.max_team_members} (policy: {seatPolicyLabel}). Seat adjustments default to Tallwave unlimited allowances.
          </p>
          <p className="text-xs text-muted-foreground">
            Subscription status: {subscriptionStatus}
          </p>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">
          Billing controls are managed through Tailored Agents finance for this tier. Contact support to adjust seats or payment methods.
        </p>
      )}
    </GlassCard>
  );
}

interface TierInsightsCardProps {
  tierDetails: TierDetails;
  featureFlags: Record<string, boolean>;
}

export function TierInsightsCard({ tierDetails, featureFlags }: TierInsightsCardProps) {
  return (
    <GlassCard className="p-6 space-y-4 md:col-span-3">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Tier Insights</h2>
          <p className="text-xs text-muted-foreground">
            User capabilities: {(tierDetails.userCapabilities ?? []).join(', ') || '—'}
          </p>
        </div>
        <span className="inline-flex items-center rounded-full bg-gradient-to-r from-[#111111] to-[#FFD400] px-3 py-1 text-xs font-semibold text-white">
          {tierDetails.organizationTier.replace('tier', 'Tier ')}
        </span>
      </div>
      <div className="grid gap-4 text-sm text-muted-foreground md:grid-cols-3">
        <TierCapabilityList capabilities={tierDetails.organizationCapabilities} />
        <TierLimitsList limits={tierDetails.limits} />
        <TierGuardrailsList guardrails={tierDetails.guardrails} featureFlags={featureFlags} />
      </div>
    </GlassCard>
  );
}

interface TierCapabilityListProps {
  capabilities?: string[] | null;
}

function TierCapabilityList({ capabilities }: TierCapabilityListProps) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-foreground">Capabilities</p>
      <ul className="mt-2 space-y-1">
        {(capabilities ?? []).slice(0, MAX_LIST_ITEMS).map((capability) => (
          <li key={capability} className="flex items-center gap-2 text-foreground">
            <CheckCircle2 className="h-3.5 w-3.5 text-accent" />
            <span className="capitalize">{capability.replace(/_/g, ' ')}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface TierLimitsListProps {
  limits?: Record<string, unknown> | null;
}

function TierLimitsList({ limits }: TierLimitsListProps) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-foreground">Limits</p>
      <ul className="mt-2 space-y-1">
        {Object.entries(limits ?? {})
          .slice(0, MAX_LIST_ITEMS)
          .map(([limitKey, limitValue]) => (
            <li key={limitKey} className="flex items-center justify-between gap-2">
              <span className="capitalize text-foreground">{limitKey.replace(/_/g, ' ')}</span>
              <span>{String(limitValue)}</span>
            </li>
          ))}
      </ul>
    </div>
  );
}

interface TierGuardrailsListProps {
  guardrails?: Record<string, string> | null;
  featureFlags: Record<string, boolean>;
}

function TierGuardrailsList({ guardrails, featureFlags }: TierGuardrailsListProps) {
  const guardrailEntries = Object.entries(guardrails ?? {});
  const hasGuardrails = guardrailEntries.length > 0;
  const featureFlagEntries = Object.entries(featureFlags);

  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-foreground">Guardrails</p>
      <ul className="mt-2 space-y-1">
        {guardrailEntries.slice(0, MAX_GUARDRAIL_ITEMS).map(([guardrailKey, guardrailValue]) => (
          <li key={guardrailKey} className="flex items-start gap-2">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
            <span className="text-foreground">{guardrailValue}</span>
          </li>
        ))}
        {!hasGuardrails && <li className="text-foreground">Standard data usage guardrails apply.</li>}
        {featureFlagEntries.length > 0 && (
          <li className="pt-3 border-t border-border">
            <p className="text-xs font-semibold uppercase tracking-wide text-foreground mb-2">Feature Flags</p>
            <ul className="space-y-1">
              {featureFlagEntries.map(([flagKey, enabled]) => (
                <li key={flagKey} className="flex items-center justify-between">
                  <span className="capitalize text-foreground">{flagKey.replace(/_/g, ' ')}</span>
                  <span className={enabled ? 'text-emerald-600 font-medium' : 'text-slate-500'}>
                    {enabled ? 'Enabled' : 'Off'}
                  </span>
                </li>
              ))}
            </ul>
          </li>
        )}
      </ul>
    </div>
  );
}

interface OverviewOnboardingSectionProps {
  onboardingProgress: OnboardingProgress | null;
  onSendOnboardingNudge: () => void;
  nudgeLoading: boolean;
  formatDate: (value?: string | null) => string;
}

export function OverviewOnboardingSection({ onboardingProgress, onSendOnboardingNudge, nudgeLoading, formatDate }: OverviewOnboardingSectionProps) {
  return (
    <div className="md:col-span-3">
      <OnboardingProgressPanel
        progress={onboardingProgress}
        onSendNudge={onSendOnboardingNudge}
        nudgeLoading={nudgeLoading}
        formatDate={formatDate}
      />
    </div>
  );
}
