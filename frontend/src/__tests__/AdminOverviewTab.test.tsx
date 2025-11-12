import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

import { OverviewTab } from '../app/admin/components/OverviewTab'
import type { FeatureFlagMap, OrganizationProfile, SeatSummary, TierDetails } from '../types'

describe('OverviewTab enterprise snapshot', () => {
  const baseProfile: OrganizationProfile = {
    id: 1,
    tenant_id: 1,
    name: 'Tallwave',
    slug: 'tallwave',
    domain: 'tallwave.ai',
    subscription_tier: 'enterprise',
    max_team_members: 5000,
    status: 'active',
    billing_details: null,
    account_settings: null,
    seat_summary: { active: 50, limit: 5000, unused_keys: 10 },
    account_overview: null,
    tier_details: null,
    feature_flags: null,
  }

  const seatUsage: SeatSummary = { active: 42, limit: 5000, unused_keys: 8 }

  const tierDetails: TierDetails = {
    userTier: 'tier3',
    organizationTier: 'tier3',
    userCapabilities: ['link_chat', 'introductions'],
    organizationCapabilities: ['corporate_connect', 'cookie_vault'],
    features: ['link_chat'],
    limits: { seats: 'Unlimited', automations: 'Unlimited' },
    automationEnabled: true,
    cookieVaultAccess: true,
    httpFallbackEnabled: true,
    safeTopicGuidance: [],
    guardrails: { security: 'enterprise' },
    organization: null,
  }

  const featureFlags: FeatureFlagMap = {
    corporate_connect: true,
    cookie_vault_admin: true,
  }

  const noop = () => {}
  const formatDate = (value?: string | null) => value ?? '—'

  it('shows Tallwave cookie compliance metrics when cookies enabled', () => {
    render(
      <OverviewTab
        profile={baseProfile}
        seatUsage={seatUsage}
        tierCapabilities={{ cookies: true, billing: true, automations: true }}
        tierDetails={tierDetails}
        totalTeamMembers={seatUsage.active}
        validCookieCount={35}
        featureFlags={featureFlags}
        statusBadgeClasses={{ active: 'bg-green-500/20 text-green-600' }}
        onNavigateToBilling={noop}
        onboardingProgress={null}
        onSendOnboardingNudge={noop}
        nudgeLoading={false}
        formatDate={formatDate}
      />,
    )

    expect(screen.getByText('Seat Utilization')).toBeInTheDocument()
    expect(
      screen.getByText((content, element) => element?.textContent === '42 / 5000'),
    ).toBeInTheDocument()
    expect(screen.getByText('Cookie Compliance')).toBeInTheDocument()
    expect(
      screen.getByText((content, element) => element?.textContent === '35 / 42'),
    ).toBeInTheDocument()
    expect(screen.getByText('Tier Insights')).toBeInTheDocument()
  })

  it('falls back to account seat limit and exposes billing CTA when cookies disabled', () => {
    const navigateMock = jest.fn()

    render(
      <OverviewTab
        profile={baseProfile}
        seatUsage={null}
        tierCapabilities={{ cookies: false, billing: false, automations: true }}
        tierDetails={null}
        totalTeamMembers={0}
        validCookieCount={0}
        featureFlags={featureFlags}
        statusBadgeClasses={{ active: 'bg-green-500/20 text-green-600' }}
        onNavigateToBilling={navigateMock}
        onboardingProgress={null}
        onSendOnboardingNudge={noop}
        nudgeLoading={false}
        formatDate={formatDate}
      />,
    )

    expect(screen.getByText('Seat Utilization')).toBeInTheDocument()
    expect(
      screen.getByText((content, element) => element?.textContent === '0 / 5000'),
    ).toBeInTheDocument()
    expect(screen.getByText('Cookie Vault Guardrails')).toBeInTheDocument()

    const reviewPlanButton = screen.getByRole('button', { name: /Review plan options/i })
    fireEvent.click(reviewPlanButton)
    expect(navigateMock).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/Billing controls are managed/)).toBeInTheDocument()
  })
})
