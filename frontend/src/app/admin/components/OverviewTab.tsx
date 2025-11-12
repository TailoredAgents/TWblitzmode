import React from 'react';
import type {
  OnboardingProgress,
  OrganizationProfile,
  SeatSummary,
  TierDetails,
} from '../../../types';
import {
  CookieStatusCard,
  OverviewOnboardingSection,
  PlanBillingCard,
  SeatUtilizationCard,
  TierInsightsCard,
} from './OverviewSections';

export type TierCapabilities = {
  cookies: boolean;
  billing: boolean;
  automations: boolean;
};

interface OverviewTabProps {
  profile: OrganizationProfile;
  seatUsage?: SeatSummary | null;
  tierCapabilities: TierCapabilities;
  tierDetails: TierDetails | null;
  totalTeamMembers: number;
  validCookieCount: number;
  featureFlags: Record<string, boolean>;
  statusBadgeClasses: Record<string, string>;
  onNavigateToBilling: () => void;
  onboardingProgress: OnboardingProgress | null;
  onSendOnboardingNudge: () => void;
  nudgeLoading: boolean;
  formatDate: (value?: string | null) => string;
}

export function OverviewTab({
  profile,
  seatUsage,
  tierCapabilities,
  tierDetails,
  totalTeamMembers,
  validCookieCount,
  featureFlags,
  statusBadgeClasses,
  onNavigateToBilling,
  onboardingProgress,
  onSendOnboardingNudge,
  nudgeLoading,
  formatDate,
}: OverviewTabProps) {
  return (
    <div className="grid gap-6 md:grid-cols-3">
      <SeatUtilizationCard
        profile={profile}
        seatUsage={seatUsage}
        statusBadgeClasses={statusBadgeClasses}
      />

      <CookieStatusCard
        hasCookieAccess={tierCapabilities.cookies}
        totalTeamMembers={totalTeamMembers}
        validCookieCount={validCookieCount}
        onNavigateToBilling={onNavigateToBilling}
      />

      <PlanBillingCard profile={profile} billingEnabled={tierCapabilities.billing} />

      {tierDetails && <TierInsightsCard tierDetails={tierDetails} featureFlags={featureFlags} />}

      <OverviewOnboardingSection
        onboardingProgress={onboardingProgress}
        onSendOnboardingNudge={onSendOnboardingNudge}
        nudgeLoading={nudgeLoading}
        formatDate={formatDate}
      />
    </div>
  );
}
