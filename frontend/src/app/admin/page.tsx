'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Clipboard,
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Users,
} from 'lucide-react';

import GlassCard from '../../components/ui/GlassCard';
import { useToastActions } from '../../components/ui/ToastContainer';
import { apiService } from '../../services/api';
import type {
  OrganizationProfile,
  RegistrationKeyListItem,
  RegistrationKeyResponse,
  SeatRequestRecord,
  TeamMember,
  User,
  OnboardingProgress,
  CookieStatus,
  CookieOverview,
  CookieEvent,
} from '../../types';
import { IntegrationHealthPanel } from '../../components/admin/IntegrationHealthPanel';
import { OverviewTab, type TierCapabilities } from './components/OverviewTab';
import { TeamMembersTab } from './components/TeamMembersTab';
import { isAdminRole } from '../../lib/roles';

type AdminTab =
  | 'Overview'
  | 'Registration Keys'
  | 'Team Members'
  | 'Cookies'
  | 'Billing'
  | 'Settings';

const billingSupportEmail =
  process.env.NEXT_PUBLIC_BILLING_SUPPORT_EMAIL ??
  process.env.NEXT_PUBLIC_SUPPORT_EMAIL ??
  'billing@tallwave.com';

type IntegrationHealthSnapshot = {
  status?: string;
  state?: string;
  result?: string;
  failures?: number;
  fail_count?: number;
  last_checked?: string;
  checked_at?: string;
  timestamp?: string;
};

type IntegrationConfigSnapshot = {
  configured?: boolean;
  status?: string;
  connected?: boolean;
};

type SeatRequestPayload = {
  seats: number;
  notes?: string;
  requesterEmail?: string;
};

const extractErrorDetail = (err: unknown): string | undefined => {
  if (err instanceof Error) {
    return err.message;
  }
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as { response?: { data?: unknown } }).response;
    const data = response?.data;
    if (data && typeof data === 'object') {
      const detailCandidate = (data as { detail?: unknown }).detail;
      if (typeof detailCandidate === 'string' && detailCandidate.trim().length > 0) {
        return detailCandidate;
      }
      const messageCandidate = (data as { message?: unknown }).message;
      if (typeof messageCandidate === 'string' && messageCandidate.trim().length > 0) {
        return messageCandidate;
      }
    }
  }
  return undefined;
};

const withFallback = (value: string | null | undefined, fallback: string): string =>
  value && value.trim().length > 0 ? value : fallback;

const statusBadgeClasses: Record<string, string> = {
  active: 'bg-emerald-500/20 text-emerald-600',
  unused: 'bg-blue-500/20 text-blue-600',
  released: 'bg-amber-500/20 text-amber-600',
  expired: 'bg-rose-500/20 text-rose-600',
  pending: 'bg-blue-500/20 text-blue-600',
  valid: 'bg-emerald-500/20 text-emerald-600',
  invalid: 'bg-rose-500/20 text-rose-600',
  missing: 'bg-slate-500/20 text-slate-600',
  deactivated: 'bg-slate-500/20 text-slate-600',
  inactive: 'bg-amber-500/20 text-amber-600',
};

function formatDate(value?: string | null): string {
  if (!value) return '—';
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString();
  } catch {
    return value;
  }
}

export default function AdminPage() {
  const { success, error } = useToastActions();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<AdminTab>('Overview');
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<OrganizationProfile | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
const [registrationKeys, setRegistrationKeys] = useState<RegistrationKeyListItem[]>([]);
const [recentKeys, setRecentKeys] = useState<RegistrationKeyResponse[]>([]);
const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
const [generateCount, setGenerateCount] = useState<number>(1);
const [keyActionLoading, setKeyActionLoading] = useState(false);
const [organizationId, setOrganizationId] = useState<number | null>(null);
const [memberActionId, setMemberActionId] = useState<number | null>(null);
const [resettingMemberId, setResettingMemberId] = useState<number | null>(null);
const roleOptions: Array<'admin' | 'user'> = ['admin', 'user'];
const formatRoleLabel = (role: string) => role.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
const [teamStatusFilter, setTeamStatusFilter] = useState<'all' | 'active' | 'deactivated'>('all');
const [teamSearch, setTeamSearch] = useState('');
const [seatRequestCount, setSeatRequestCount] = useState<number | undefined>();
const [seatRequestNotes, setSeatRequestNotes] = useState('');
const [seatRequestSubmitting, setSeatRequestSubmitting] = useState(false);
const [onboardingProgress, setOnboardingProgress] = useState<OnboardingProgress | null>(null);
const [nudgeLoading, setNudgeLoading] = useState(false);
const [cookieStatuses, setCookieStatuses] = useState<CookieStatus[]>([]);
const [cookieOverview, setCookieOverview] = useState<CookieOverview | null>(null);
const [selectedCookieJar, setSelectedCookieJar] = useState<CookieStatus | null>(null);
const [cookieEvents, setCookieEvents] = useState<CookieEvent[]>([]);
const [cookieEventsLoading, setCookieEventsLoading] = useState(false);
const [cookieActionId, setCookieActionId] = useState<number | null>(null);
const seatRequestSectionRef = useRef<HTMLDivElement | null>(null);
const [integrationHealth, setIntegrationHealth] = useState<Record<string, unknown> | null>(null);
const [integrationConfig, setIntegrationConfig] = useState<Record<string, unknown> | null>(null);
const [integrationLoading, setIntegrationLoading] = useState(false);

  const tierCapabilities = useMemo<TierCapabilities>(() => {
    const tierDetails = profile?.tier_details;
    const flags = profile?.feature_flags ?? {};

    if (tierDetails) {
      const organizationTier = tierDetails.organizationTier ?? 'tier1';
      const cookiesEnabled = [
        tierDetails.cookieVaultAccess,
        flags.cookie_vault_admin,
        flags.cookie_collection,
      ].some(Boolean);
      const billingEnabled = [
        flags.corporate_connect,
        organizationTier === 'tier2',
        organizationTier === 'tier3',
      ].some(Boolean);
      const automationsEnabled = [
        tierDetails.automationEnabled,
        flags.corporate_connect,
      ].some(Boolean);
      return { cookies: cookiesEnabled, billing: billingEnabled, automations: automationsEnabled };
    }

    const tier = (profile?.subscription_tier ?? 'default').toLowerCase();
    const capabilityMap = {
      default: { cookies: false, billing: false, automations: false },
      starter: { cookies: false, billing: false, automations: false },
      growth: { cookies: true, billing: false, automations: true },
      professional: { cookies: true, billing: true, automations: true },
      enterprise: { cookies: true, billing: true, automations: true },
      custom: { cookies: true, billing: true, automations: true },
    } as const satisfies Record<string, TierCapabilities>;

    if (tier in capabilityMap) {
      return capabilityMap[tier as keyof typeof capabilityMap];
    }

    return capabilityMap.default;
  }, [profile?.tier_details, profile?.feature_flags, profile?.subscription_tier]);

  const loadIntegrationStatus = useCallback(async () => {
    setIntegrationLoading(true);
    try {
      const [healthResp, configResp] = await Promise.all([
        apiService.getIntegrationHealthSummary(),
        apiService.getIntegrationConfigSummary(),
      ]);
      setIntegrationHealth(healthResp.data ?? null);
      setIntegrationConfig(configResp.data ?? null);
    } catch (err) {
      console.error('Failed to load integration status', err);
      error('Unable to load integration validation results', 'Please refresh and try again.');
    } finally {
      setIntegrationLoading(false);
    }
  }, [error]);

  useEffect(() => {
    if (activeTab === 'Settings') {
      void loadIntegrationStatus();
    }
  }, [activeTab, loadIntegrationStatus]);

  const accountOverview = profile?.account_overview ?? null;
  const tierDetails = profile?.tier_details ?? null;
  const featureFlags = profile?.feature_flags ?? {};
  const seatUsage = useMemo(() => profile?.seat_summary ?? null, [profile]);
  const filteredTeamMembers = useMemo(() => {
    const term = teamSearch.trim().toLowerCase();
    return teamMembers.filter((member) => {
      const normalizedStatus = (member.status ?? 'active').toLowerCase();
      const statusMatches =
        teamStatusFilter === 'all' ||
        normalizedStatus === teamStatusFilter;
      const searchMatches =
        !term ||
        member.name.toLowerCase().includes(term) ||
        (member.email ?? '').toLowerCase().includes(term);
      return statusMatches && searchMatches;
    });
  }, [teamMembers, teamStatusFilter, teamSearch]);
  const seatRequests = useMemo<SeatRequestRecord[]>(() => accountOverview?.seat_requests ?? [], [accountOverview]);
  const integrationEntries = useMemo(() => {
    if (!integrationHealth && !integrationConfig) {
      return [] as Array<{
        provider: string;
        status: string;
        failures: number;
        lastChecked: string | null;
        configured: boolean;
      }>;
    }

    const healthEntries = new Map<string, IntegrationHealthSnapshot>(
      Object.entries(integrationHealth ?? {}) as Array<[string, IntegrationHealthSnapshot]>
    );
    const configEntries = new Map<string, IntegrationConfigSnapshot>(
      Object.entries(integrationConfig ?? {}) as Array<[string, IntegrationConfigSnapshot]>
    );
    const providers = new Set([...healthEntries.keys(), ...configEntries.keys()]);

    return Array.from(providers).map((provider) => {
      const health = healthEntries.get(provider) ?? {};
      const config = configEntries.get(provider) ?? {};
      const statusSource = health.status ?? health.state ?? health.result ?? 'unknown';
      const failures = Number(health.failures ?? health.fail_count ?? 0);
      const lastChecked = (health.last_checked ?? health.checked_at ?? health.timestamp ?? null) as
        | string
        | null;
      const configured = [
        config.configured,
        config.connected,
        config.status === 'configured',
        config.status === 'connected',
      ].some(Boolean);

      return {
        provider,
        status: String(statusSource),
        failures,
        lastChecked,
        configured,
      };
    });
  }, [integrationHealth, integrationConfig]);

  const scrollToSeatRequest = () => {
    seatRequestSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const activeSeatCount = seatUsage?.active ?? 0;
  const currentSeatLimit = seatUsage?.limit ?? profile?.max_team_members ?? 0;
  const accountStatus = accountOverview?.account_status ?? 'active';
  const subscriptionStatus = accountOverview?.subscription_status ?? 'active';
  const seatPolicy = accountOverview?.seat_policy ?? null;
  const seatPolicyLabel =
    (seatPolicy?.description ?? seatPolicy?.type ?? 'Unlimited').toString();
  const seatPolicyMax = typeof seatPolicy?.maxSeats === 'number' ? seatPolicy.maxSeats : null;

const loadRegistrationKeys = useCallback(async (orgId: number) => {
  try {
    const response = await apiService.getRegistrationKeys(orgId);
    setRegistrationKeys(response.data ?? []);
  } catch (err) {
    console.error('Failed to load registration keys', err);
    error('Unable to load registration keys');
  }
}, [error]);

const loadTeamMembers = useCallback(async (orgId: number) => {
  try {
    const response = await apiService.getTeamMembers(orgId);
    setTeamMembers(response.data ?? []);
  } catch (err) {
    console.error('Failed to load team members', err);
    error('Unable to load team members');
  }
}, [error]);

const loadOnboardingProgress = useCallback(async (orgId: number) => {
  try {
    const response = await apiService.getOnboardingProgress(orgId);
    setOnboardingProgress(response.data ?? null);
  } catch (err) {
    console.error('Failed to load onboarding progress', err);
    error('Unable to load onboarding progress');
  }
}, [error]);

const loadCookieData = useCallback(async (orgId: number) => {
  try {
    const [statusesResp, overviewResp] = await Promise.all([
      apiService.listCookieStatuses(orgId),
      apiService.getCookieOverview(orgId),
    ]);
    setCookieStatuses(statusesResp.data ?? []);
    setCookieOverview(overviewResp.data ?? null);
  } catch (err) {
    console.error('Failed to load cookie governance data', err);
    error('Unable to load cookie governance data');
  }
}, [error]);

const loadCookieEvents = useCallback(async (orgId: number, jarId: number) => {
  setCookieEventsLoading(true);
  try {
    const response = await apiService.listCookieEvents(orgId, jarId);
    setCookieEvents(response.data ?? []);
  } catch (err) {
    console.error('Failed to load cookie events', err);
    error('Unable to load cookie event history');
  } finally {
    setCookieEventsLoading(false);
  }
}, [error]);

const handleScrapingPolicyToggle = useCallback(async () => {
  if (!organizationId || !cookieOverview) return;
  try {
    const response = await apiService.updateScrapingPolicy(organizationId, {
      paused: !cookieOverview.scraping_paused,
      reason: !cookieOverview.scraping_paused ? 'Temporarily paused via admin console' : null,
    });
    setCookieOverview(response.data ?? null);
    success(!cookieOverview.scraping_paused ? 'Scraping paused' : 'Scraping resumed');
  } catch (err) {
    console.error('Failed to update scraping policy', err);
    error('Unable to update scraping policy');
  }
}, [organizationId, cookieOverview, success, error]);

const handleSelectCookieJar = async (jar: CookieStatus) => {
  if (!organizationId || !jar.id) return;
  setSelectedCookieJar(jar);
  await loadCookieEvents(organizationId, jar.id);
};

const handleRevalidateCookieJar = async (jarId: number) => {
  if (!organizationId) return;
  setCookieActionId(jarId);
  try {
    await apiService.revalidateCookieJar(organizationId, jarId);
    await loadCookieData(organizationId);
    if (selectedCookieJar?.id === jarId) {
      await loadCookieEvents(organizationId, jarId);
    }
    success('Cookie jar revalidated');
  } catch (err) {
    console.error('Failed to revalidate cookie jar', err);
    error('Unable to revalidate cookie jar');
  } finally {
    setCookieActionId(null);
  }
};

const loadAdminData = useCallback(async () => {
  setLoading(true);
  try {
    const [userResp, profileResp] = await Promise.all([
      apiService.getCurrentUser(),
      apiService.getOrganizationProfile(),
    ]);

    const fetchedUser = userResp.data as unknown as User | undefined;
    if (fetchedUser) {
      setCurrentUser(fetchedUser);
      if (!isAdminRole(fetchedUser.role)) {
        error(
          'Admin access required',
          'Switch to an admin account to manage organization settings.'
        );
        setLoading(false);
        if (typeof window !== 'undefined') {
          window.setTimeout(() => {
            router.replace('/dashboard');
          }, 1500);
        }
        return;
      }
    }

    const fetchedProfile = profileResp.data as OrganizationProfile | undefined;
    if (fetchedProfile) {
      setProfile(fetchedProfile);
      setOrganizationId(fetchedProfile.id);
      await Promise.all([
        loadRegistrationKeys(fetchedProfile.id),
        loadTeamMembers(fetchedProfile.id),
      ]);
      await Promise.all([
        loadOnboardingProgress(fetchedProfile.id),
        loadCookieData(fetchedProfile.id),
      ]);
    }
  } catch (err) {
    console.error('Failed to load admin context', err);
    error('Unable to load admin data', 'Please refresh and try again.');
  } finally {
    setLoading(false);
  }
}, [
  error,
  router,
  loadRegistrationKeys,
  loadTeamMembers,
  loadOnboardingProgress,
  loadCookieData,
]);

  useEffect(() => {
    void loadAdminData();
  }, [loadAdminData]);
  
const refreshOrganizationProfile = async () => {
  try {
    const response = await apiService.getOrganizationProfile();
    const refreshedProfile = response.data as OrganizationProfile | undefined;
    if (refreshedProfile) {
      setProfile(refreshedProfile);
      setOrganizationId(refreshedProfile.id);
      await Promise.all([
        loadRegistrationKeys(refreshedProfile.id),
        loadTeamMembers(refreshedProfile.id),
        loadCookieData(refreshedProfile.id),
      ]);
      await loadOnboardingProgress(refreshedProfile.id);
    }
  } catch (err) {
    console.error('Failed to refresh organization profile', err);
  }
};

const handleRoleChange = async (memberId: number, newRole: 'admin' | 'user') => {
  if (!organizationId) return;
  setMemberActionId(memberId);
  try {
    const response = await apiService.updateTeamMember(organizationId, memberId, { role: newRole });
    const updatedMember = response.data;
    if (updatedMember) {
      setTeamMembers((prev) => prev.map((member) => (member.id === memberId ? updatedMember : member)));
      success('Role updated');
    }
  } catch (err) {
    console.error('Failed to update role', err);
    error('Unable to update role');
  } finally {
    setMemberActionId(null);
  }
};

const handleToggleStatus = async (member: TeamMember) => {
  if (!organizationId) return;
  const nextStatus = member.status === 'active' ? 'deactivated' : 'active';
  setMemberActionId(member.id);
  try {
    const response = await apiService.updateTeamMember(organizationId, member.id, { status: nextStatus });
    const updatedMember = response.data;
    if (updatedMember) {
      setTeamMembers((prev) => prev.map((item) => (item.id === member.id ? updatedMember : item)));
      await loadRegistrationKeys(organizationId);
      await refreshOrganizationProfile();
      success(`Member ${nextStatus === 'active' ? 'activated' : 'deactivated'}`);
    }
  } catch (err: unknown) {
    console.error('Failed to update status', err);
    const message = extractErrorDetail(err) ?? 'Unable to update member status';
    error('Update failed', message);
  } finally {
    setMemberActionId(null);
  }
};

const handleResetPassword = async (memberId: number) => {
  if (!organizationId) return;
  setResettingMemberId(memberId);
  try {
    const response = await apiService.resetTeamMemberPassword(organizationId, memberId);
    const data = response.data;
    if (data) {
      const clipboardValue = data.reset_url ?? data.token;
      try {
        await navigator.clipboard.writeText(clipboardValue);
        success('Password reset token copied to clipboard');
      } catch (clipboardError) {
        console.error('Clipboard write failed', clipboardError);
        success('Password reset token generated', `Token: ${data.token}`);
      }
    }
  } catch (err) {
    console.error('Failed to reset password', err);
    error('Unable to generate reset token');
  } finally {
    setResettingMemberId(null);
  }
};

const handleSendOnboardingNudge = async () => {
  if (!organizationId) return;
  setNudgeLoading(true);
  try {
    const response = await apiService.sendOnboardingReminder(organizationId);
    if (response.error) {
      error('Unable to send onboarding reminder', response.error);
    } else {
      const payload = response.data ?? null;
      const message = payload?.message ?? response.message ?? 'Onboarding reminder sent.';
      success('Reminder sent', message);
      await loadOnboardingProgress(organizationId);
    }
  } catch (err) {
    console.error('Failed to send onboarding reminder', err);
    error('Unable to send onboarding reminder');
  } finally {
    setNudgeLoading(false);
  }
};

  const handleGenerateKeys = async () => {
    if (!organizationId) return;
    if (generateCount < 1) {
      error('Enter a valid key count');
      return;
    }
    setKeyActionLoading(true);
    try {
      const response = await apiService.generateRegistrationKeys(organizationId, generateCount);
      const generated = response.data ?? [];
      setRecentKeys(generated);
      await loadRegistrationKeys(organizationId);
      success(
        `Generated ${generated.length} registration ${generated.length === 1 ? 'key' : 'keys'}`,
        'Share these keys securely with new team members.'
      );
    } catch (err) {
      console.error('Failed to generate keys', err);
      error('Unable to generate registration keys', 'Please check seat limits or try again later.');
    } finally {
      setKeyActionLoading(false);
    }
  };

  const handleReleaseKey = async (keyId: number) => {
    if (!organizationId) return;
    setKeyActionLoading(true);
    try {
      await apiService.releaseRegistrationKey(organizationId, keyId);
      success('Seat released', 'The registration key is now available for reuse.');
      await loadRegistrationKeys(organizationId);
    } catch (err) {
      console.error('Failed to release key', err);
      error('Unable to release key right now');
    } finally {
      setKeyActionLoading(false);
    }
  };

  const handleCopy = async (value: string, successMessage = 'Copied to clipboard') => {
    if (!value) return;

    try {
      if (!navigator.clipboard) {
        throw new Error('Clipboard API not available');
      }
      await navigator.clipboard.writeText(value);
      success(successMessage);
    } catch (err) {
      console.error('Clipboard error', err);
      error('Unable to copy automatically', 'We selected the text so you can copy it manually.');

      const textArea = document.createElement('textarea');
      textArea.value = value;
      textArea.style.position = 'fixed';
      textArea.style.opacity = '0';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      try {
        document.execCommand('copy');
        success(`${successMessage} (fallback)`);
      } catch (fallbackError) {
        console.error('Fallback copy failed', fallbackError);
      } finally {
        document.body.removeChild(textArea);
      }
    }
  };

  const buildShareUrl = useCallback((path: string | null | undefined) => {
    if (!path) return '';
    try {
      if (typeof window === 'undefined') {
        return path;
      }
      return new URL(path, window.location.origin).toString();
    } catch (err) {
      console.error('Failed to construct registration key share URL', err);
      return path;
    }
  }, []);

  const formatRegistrationExpiry = useCallback((value?: string | null) => {
    if (!value) return 'Link deactivates after first download.';
    try {
      const formatted = new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(new Date(value));
      return `Link expires after first download or on ${formatted}.`;
    } catch (err) {
      console.error('Failed to format registration key expiry', err);
      return 'Link deactivates after first download.';
    }
  }, []);

const handleRefresh = async () => {
  if (!organizationId) return;
  await Promise.all([
    loadRegistrationKeys(organizationId),
    loadTeamMembers(organizationId),
    refreshOrganizationProfile(),
    loadOnboardingProgress(organizationId),
  ]);
  success('Data refreshed');
};

const handleNavigateToRegistrationKeys = () => {
  setActiveTab('Registration Keys');
};

const handleSubmitSeatRequest = async () => {
  if (!organizationId) return;
  setSeatRequestSubmitting(true);
  try {
    if (!seatRequestCount) {
      error('Please specify the number of seats needed');
      setSeatRequestSubmitting(false);
      return;
    }

    const requestPayload: SeatRequestPayload = {
      seats: seatRequestCount,
    };

    const trimmedNotes = seatRequestNotes.trim();
    if (trimmedNotes.length > 0) {
      requestPayload.notes = trimmedNotes;
    }

    if (currentUser?.email) {
      requestPayload.requesterEmail = currentUser.email;
    }

    const response = await apiService.requestSeatUpgrade(organizationId, requestPayload);
    if (response.data) {
      if (Array.isArray(response.data.alert_failures) && response.data.alert_failures.length > 0) {
        const failureSummary = response.data.alert_failures.join(', ');
        success('Seat request logged, but some alerts failed to send.');
        error('Alert delivery issue', `We could not notify: ${failureSummary}. Please reach out manually if needed.`);
      } else {
        success('Seat request submitted');
      }
      await refreshOrganizationProfile();
      setSeatRequestCount(undefined);
      setSeatRequestNotes('');
    } else {
      error('Unable to submit request', withFallback(response.error ?? null, 'Please try again later.'));
    }
  } catch (err) {
    console.error('Seat request failed', err);
    const message = extractErrorDetail(err) ?? 'Please try again later.';
    error('Unable to submit request', message);
  } finally {
    setSeatRequestSubmitting(false);
  }
};

  const validCookieCount = useMemo(
    () => cookieStatuses.filter((jar) => jar.status === 'valid').length,
    [cookieStatuses]
  );

  // Role guards - check if user has admin access
  const hasAdminAccess = useMemo(() => {
    if (!currentUser) return false;
    return isAdminRole(currentUser.role);
  }, [currentUser]);

  // Filter tabs based on role permissions
  const accessibleTabs = useMemo(() => {
    if (!currentUser) return [] as AdminTab[];

    const tabs: AdminTab[] = ['Overview', 'Registration Keys', 'Team Members'];
    if (tierCapabilities.cookies) {
      tabs.push('Cookies');
    }

    if (currentUser.role === 'admin') {
      if (tierCapabilities.billing) {
        tabs.push('Billing');
      }
      tabs.push('Settings');
    }

    return tabs;
  }, [currentUser, tierCapabilities]);

  useEffect(() => {
    if (activeTab && !accessibleTabs.includes(activeTab)) {
      setActiveTab(accessibleTabs[0] ?? 'Overview');
    }
  }, [accessibleTabs, activeTab]);

  // Admin access audit logging
  const logAdminAccess = useCallback((action: string, details?: Record<string, unknown>) => {
    if (process.env.NODE_ENV !== 'production') {
      console.warn(
        `[Admin Access Audit] User: ${currentUser?.email}, Role: ${currentUser?.role}, Action: ${action}`,
        details
      );
    }
    // In production, this would send to an audit logging service
  }, [currentUser]);

  // Handle tab changes with audit logging
  const handleTabChange = useCallback((tab: AdminTab) => {
    if (!accessibleTabs.includes(tab)) {
      error('Access Denied', `You don't have permission to access the ${tab} tab.`);
      logAdminAccess('ACCESS_DENIED', { attemptedTab: tab });
      return;
    }

    setActiveTab(tab);
    logAdminAccess('TAB_ACCESS', { tab });
  }, [accessibleTabs, error, logAdminAccess]);

  if (loading || !profile) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <GlassCard className="p-10 flex items-center gap-3">
          <Loader2 className="w-5 h-5 animate-spin text-primary" />
          <span className="text-sm text-muted-foreground">Loading admin portal…</span>
        </GlassCard>
      </div>
    );
  }

  // Access denied for non-admin users
  if (!hasAdminAccess) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <GlassCard className="p-10 max-w-md text-center space-y-4">
          <div className="flex justify-center">
            <ShieldCheck className="w-12 h-12 text-amber-500" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-foreground mb-2">Access Restricted</h2>
            <p className="text-sm text-muted-foreground mb-4">
              This area requires administrator privileges. Only users with the 'admin' role can access billing and administrative features.
            </p>
            <p className="text-xs text-muted-foreground">
              Current role: <span className="font-medium capitalize">{withFallback(currentUser?.role ?? null, 'unknown')}</span>
            </p>
          </div>
          <button
            onClick={() => window.history.back()}
            className="px-4 py-2 text-sm font-medium text-primary border border-primary/20 rounded-lg hover:bg-primary/10 transition-colors"
          >
            Go Back
          </button>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background px-4 py-10">
      <div className="max-w-6xl mx-auto space-y-8">
        <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-primary">Organization Admin</h1>
            <p className="text-sm text-muted-foreground">
              Monitor team seats and review organization details for{' '}
              <span className="font-medium text-foreground">{profile.name}</span>.
            </p>
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg border border-border/40 hover:border-border transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </header>

        <nav className="flex flex-wrap gap-2">
          {accessibleTabs.map((tab) => {
            const isActive = tab === activeTab;
            const isProtectedTab = tab === 'Billing' || tab === 'Settings';
            return (
              <button
                key={tab}
                type="button"
                onClick={() => handleTabChange(tab)}
                className={`relative px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                  isActive ? 'bg-primary text-primary-foreground shadow-sm' : 'bg-muted/50 text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab}
                {isProtectedTab && (
                  <ShieldCheck className="w-3 h-3 inline-block ml-1 opacity-60" />
                )}
              </button>
            );
          })}
        </nav>

        {activeTab === 'Overview' && (
          <OverviewTab
            profile={profile}
            seatUsage={seatUsage}
            tierCapabilities={tierCapabilities}
            tierDetails={tierDetails}
            totalTeamMembers={teamMembers.length}
            validCookieCount={validCookieCount}
            featureFlags={featureFlags}
            statusBadgeClasses={statusBadgeClasses}
            onNavigateToBilling={() => handleTabChange('Billing')}
            onboardingProgress={onboardingProgress}
            onSendOnboardingNudge={handleSendOnboardingNudge}
            nudgeLoading={nudgeLoading}
            formatDate={formatDate}
          />
        )}

        {activeTab === 'Registration Keys' && (
          <div className="space-y-6">
            <GlassCard className="p-6 space-y-5">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-foreground">Registration Keys (Retired)</h2>
                  <p className="text-sm text-muted-foreground">
                    Tallwave now uses self‑service seating. Teammates can self‑seat: Login → enter
                    <span className="mx-1 font-mono">Tallwave123</span>→ click “+ Team member”.
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">No action required.</div>
              </div>

              {recentKeys.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-primary">
                    <ArrowRight className="w-4 h-4" />
                    Newly generated keys (copy and distribute securely):
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    {recentKeys.map((key) => {
                      const shareUrl = buildShareUrl(key.download_url);
                      return (
                        <div
                          key={key.id}
                          className="space-y-2 rounded-lg border border-border/30 bg-muted/20 px-3 py-2 text-xs"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 space-y-1">
                              <span className="text-[11px] font-semibold uppercase text-muted-foreground">Key</span>
                              <div className="rounded-md border border-border/40 bg-background/80 px-2 py-1.5">
                                <span className="break-all font-mono text-xs text-foreground">{key.key}</span>
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => handleCopy(key.key, 'Registration key copied')}
                              className="inline-flex items-center gap-1 rounded-md border border-primary/40 px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/10"
                            >
                              <Clipboard className="w-3 h-3" />
                              Copy
                            </button>
                          </div>
                          {key.download_url && (
                            <div className="flex flex-col gap-2 rounded-md border border-border/40 bg-background/50 px-2 py-2">
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-[11px] font-semibold text-muted-foreground">Secure link</span>
                                <button
                                  type="button"
                                  onClick={() => handleCopy(shareUrl, 'Secure link copied')}
                                  className="inline-flex items-center gap-1 rounded-md border border-primary/30 px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/10"
                                >
                                  <Clipboard className="w-3 h-3" />
                                  Copy link
                                </button>
                              </div>
                              <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                                <a
                                  href={key.download_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 text-primary hover:text-primary/80"
                                >
                                  <ArrowRight className="h-3 w-3" />
                                  Open link
                                </a>
                                <span className="text-right">{formatRegistrationExpiry(key.expires_at)}</span>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-muted-foreground border-b border-border/20">
                    <tr>
                      <th className="py-2 pr-4">Key</th>
                      <th className="py-2 pr-4">Status</th>
                      <th className="py-2 pr-4">Assigned To</th>
                      <th className="py-2 pr-4">Created</th>
                      <th className="py-2 pr-4">Expires</th>
                      <th className="py-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/20">
                    {registrationKeys.map((key) => {
                      const badgeClass = statusBadgeClasses[key.status] ?? 'bg-slate-500/20 text-slate-600';
                      return (
                        <tr key={key.id}>
                          <td className="py-2 pr-4 font-mono text-xs">{key.masked_key}</td>
                          <td className="py-2 pr-4">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs ${badgeClass}`}>
                              {key.status}
                            </span>
                          </td>
                          <td className="py-2 pr-4 text-xs">
                            {key.assigned_team_member_id ? `Member #${key.assigned_team_member_id}` : 'Unassigned'}
                          </td>
                          <td className="py-2 pr-4 text-xs text-muted-foreground">
                            {formatDate(key.created_at)}
                          </td>
                          <td className="py-2 pr-4 text-xs text-muted-foreground">
                            {formatDate(key.expires_at)}
                          </td>
                          <td className="py-2 text-right">
                            <div className="inline-flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => handleCopy(key.masked_key)}
                                className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80"
                              >
                                <Clipboard className="w-3 h-3" />
                                Copy Mask
                              </button>
                              {key.status === 'active' && (
                                <button
                                  type="button"
                                  onClick={() => handleReleaseKey(key.id)}
                                  className="inline-flex items-center gap-1 text-xs font-medium text-rose-500 hover:text-rose-400"
                                >
                                  Release
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {registrationKeys.length === 0 && (
                  <div className="py-6 text-center text-sm text-muted-foreground">
                    Registration keys are no longer required. Teammates can self‑seat via Login → “+ Team member”.
                  </div>
                )}
              </div>
            </GlassCard>
          </div>
        )}

        {activeTab === 'Team Members' && (
          <TeamMembersTab
            members={teamMembers}
            filteredMembers={filteredTeamMembers}
            statusFilter={teamStatusFilter}
            onStatusFilterChange={setTeamStatusFilter}
            searchQuery={teamSearch}
            onSearchChange={setTeamSearch}
            roleOptions={roleOptions}
            formatRoleLabel={formatRoleLabel}
            statusBadgeClasses={statusBadgeClasses}
            memberActionId={memberActionId}
            resettingMemberId={resettingMemberId}
            onRoleChange={handleRoleChange}
            onToggleStatus={handleToggleStatus}
            onResetPassword={handleResetPassword}
            formatDate={formatDate}
          />
        )}

        {activeTab === 'Cookies' && (
          <GlassCard className="p-6 space-y-6">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-foreground">LinkedIn Cookie Governance</h2>
                <p className="text-sm text-muted-foreground">
                  Monitor encryption status, expiry timelines, and scrape readiness for each team member.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => organizationId && loadCookieData(organizationId)}
                  className="inline-flex items-center gap-2 rounded-lg border border-border/30 bg-muted/20 px-3 py-1.5 text-xs font-medium hover:bg-muted/30"
                >
                  <RefreshCw className="w-3 h-3" /> Refresh
                </button>
                <button
                  type="button"
                  onClick={handleScrapingPolicyToggle}
                  className="inline-flex items-center gap-2 rounded-lg border border-border/30 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10"
                  disabled={!cookieOverview}
                >
                  {cookieOverview?.scraping_paused ? 'Resume Scraping' : 'Pause Scraping'}
                </button>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-5">
              {[
                { label: 'Total Jars', value: cookieOverview?.total ?? 0 },
                { label: 'Valid', value: cookieOverview?.valid ?? 0 },
                { label: 'Pending', value: cookieOverview?.pending ?? 0 },
                { label: 'Invalid', value: cookieOverview?.invalid ?? 0 },
                { label: 'Expiring Soon', value: cookieOverview?.expiring_soon ?? 0 },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-border/20 bg-muted/10 px-4 py-3">
                  <p className="text-xs text-muted-foreground">{item.label}</p>
                  <p className="text-lg font-semibold text-foreground">{item.value}</p>
                </div>
              ))}
            </div>

            {cookieOverview?.scraping_paused && (
              <div className="rounded-lg border border-amber-400/60 bg-amber-50 px-4 py-3 text-sm text-amber-700">
                <p className="font-medium">Scraping Paused</p>
                <p>
                  {withFallback(
                    cookieOverview.scraping_paused_reason ?? null,
                    'LinkedIn scraping is currently paused for this tenant.'
                  )}
                  {cookieOverview.scraping_paused_at && (
                    <span className="ml-1">(since {formatDate(cookieOverview.scraping_paused_at)})</span>
                  )}
                </p>
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-muted-foreground border-b border-border/20">
                  <tr>
                    <th className="py-2 pr-4">Team Member</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Detail</th>
                    <th className="py-2 pr-4">Expires</th>
                    <th className="py-2 pr-4">Last Validated</th>
                    <th className="py-2 pr-4">Usage</th>
                    <th className="py-2 pr-4">Errors</th>
                    <th className="py-2 pl-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/20">
                  {cookieStatuses.map((jar) => {
                    const badge = statusBadgeClasses[jar.status ?? 'missing'] ?? 'bg-slate-500/20 text-slate-600';
                    const isActionLoading = cookieActionId === jar.id;
                    const hasName = [jar.first_name, jar.last_name].some(
                      (part) => typeof part === 'string' && part.trim().length > 0
                    );
                    const rawLabel = hasName
                      ? `${jar.first_name ?? ''} ${jar.last_name ?? ''}`.trim()
                      : jar.email ?? 'Unknown member';
                    const memberLabel = rawLabel.length > 0 ? rawLabel : 'Unknown member';

                    return (
                      <tr key={jar.id ?? memberLabel}>
                        <td className="py-2 pr-4">
                          <div className="flex flex-col">
                            <span className="font-medium text-foreground">{memberLabel}</span>
                            <span className="text-xs text-muted-foreground">{jar.email ?? '—'}</span>
                          </div>
                        </td>
                        <td className="py-2 pr-4">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs ${badge}`}>
                            {jar.status ?? 'missing'}
                          </span>
                        </td>
                        <td className="py-2 pr-4 text-xs text-muted-foreground">{jar.status_detail ?? '—'}</td>
                        <td className="py-2 pr-4 text-xs text-muted-foreground">{formatDate(jar.expires_at)}</td>
                        <td className="py-2 pr-4 text-xs text-muted-foreground">{formatDate(jar.last_validated_at)}</td>
                        <td className="py-2 pr-4 text-xs text-muted-foreground">{jar.usage_count ?? 0}</td>
                        <td className="py-2 pr-4 text-xs text-muted-foreground">
                          {jar.error_count ?? 0}
                          {jar.last_error && <span className="block text-[11px] text-amber-700">{jar.last_error}</span>}
                        </td>
                        <td className="py-2 pl-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => handleSelectCookieJar(jar)}
                              className="rounded-lg border border-border/30 bg-muted/20 px-3 py-1 text-xs hover:bg-muted/30"
                            >
                              View Activity
                            </button>
                            <button
                              type="button"
                              onClick={() => jar.id && handleRevalidateCookieJar(jar.id)}
                              disabled={isActionLoading}
                              className="rounded-lg border border-border/30 bg-primary/10 px-3 py-1 text-xs text-primary hover:bg-primary/20 disabled:opacity-50"
                            >
                              {isActionLoading ? 'Revalidating…' : 'Revalidate'}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {cookieStatuses.length === 0 && (
                <div className="py-6 text-center text-sm text-muted-foreground">
                  No cookie jars on file yet. Ask team members to upload their LinkedIn cookies from the settings page.
                </div>
              )}
            </div>

            {selectedCookieJar && (
              <div className="rounded-xl border border-border/20 bg-muted/10 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">Activity Log</h3>
                    <p className="text-xs text-muted-foreground">
                      Recent events for {selectedCookieJar.email ?? 'team member'} (Jar #{selectedCookieJar.id})
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedCookieJar(null)}
                    className="text-xs text-muted-foreground hover:text-foreground"
                  >
                    Close
                  </button>
                </div>
                {cookieEventsLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading activity…
                  </div>
                ) : cookieEvents.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No recent events recorded.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {cookieEvents.map((event) => (
                      <li key={`${event.event_type}-${event.created_at}`} className="rounded-lg border border-border/20 bg-background/40 px-3 py-2">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-foreground">{event.event_type}</span>
                          <span className="text-xs text-muted-foreground">{formatDate(event.created_at)}</span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1">{event.message ?? 'No additional details provided.'}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </GlassCard>
        )}

        {activeTab === 'Billing' && (
          <GlassCard className="p-6 space-y-6">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <ShieldCheck className="w-5 h-5 text-primary" />
                <div>
                  <h2 className="text-lg font-semibold text-foreground">Seat Policy & Billing</h2>
                  <p className="text-sm text-muted-foreground">
                    Tallwave finance manages invoicing offline. Review usage and request changes from this console.
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-amber-400/60 bg-amber-50 p-4 text-sm text-amber-700">
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 mt-0.5" />
                <div className="space-y-1">
                  <p>Seat allotments default to unlimited under the Tallwave enterprise agreement.</p>
                  <p>Contact {billingSupportEmail} if you need formal billing or invoicing adjustments.</p>
                </div>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-lg border border-border/20 bg-muted/20 p-4 space-y-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Seat Utilization</p>
                <p className="text-sm font-semibold text-foreground">
                  {activeSeatCount} / {currentSeatLimit}
                </p>
                <p className="text-xs text-muted-foreground">
                  Active teammates relative to the configured allowance.
                </p>
              </div>
              <div className="rounded-lg border border-border/20 bg-muted/20 p-4 space-y-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Seat Policy</p>
                <p className="text-sm font-semibold text-foreground">{seatPolicyLabel}</p>
                <p className="text-xs text-muted-foreground">
                  {seatPolicyMax
                    ? `Soft cap of ${seatPolicyMax} seats — Tallwave can extend as needed.`
                    : 'No hard cap enforced for Tallwave.'}
                </p>
              </div>
              <div className="rounded-lg border border-border/20 bg-muted/20 p-4 space-y-2">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Account Status</p>
                <p className="text-sm font-semibold text-foreground">{accountStatus}</p>
                <p className="text-xs text-muted-foreground">Subscription status: {subscriptionStatus}</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={scrollToSeatRequest}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <ArrowRight className="w-4 h-4" />
                Request Seats
              </button>
              <button
                type="button"
                onClick={handleNavigateToRegistrationKeys}
                className="inline-flex items-center gap-2 rounded-lg border border-border/40 px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
              >
                <KeyRound className="w-4 h-4" />
                Issue Registration Keys
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('Team Members')}
                className="inline-flex items-center gap-2 rounded-lg border border-border/40 px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"
              >
                <Users className="w-4 h-4" />
                Manage Roster
              </button>
            </div>

            <div ref={seatRequestSectionRef} className="rounded-lg border border-border/20 bg-muted/10 p-4 space-y-3">
              <h3 className="text-sm font-semibold text-foreground">Request Additional Seats</h3>
              <p className="text-xs text-muted-foreground">
                Submit a request to expand your seat allocation. Tallwave operations responds within one business day.
              </p>
              <div className="grid gap-3 md:grid-cols-3">
                <div className="md:col-span-1">
                  <label className="block text-xs font-medium text-muted-foreground mb-1" htmlFor="seat-request-count">
                    Seats Required
                  </label>
                  <input
                    id="seat-request-count"
                    type="number"
                    min={1}
                    value={seatRequestCount ?? ''}
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      setSeatRequestCount(Number.isNaN(value) || value <= 0 ? undefined : value);
                    }}
                    className="w-full rounded-lg border border-border/30 bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                    placeholder="e.g. 5"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="block text-xs font-medium text-muted-foreground mb-1" htmlFor="seat-request-notes">
                    Notes (optional)
                  </label>
                  <textarea
                    id="seat-request-notes"
                    value={seatRequestNotes}
                    onChange={(event) => setSeatRequestNotes(event.target.value)}
                    rows={2}
                    className="w-full rounded-lg border border-border/30 bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                    placeholder="Include context such as hiring plans or timelines"
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleSubmitSeatRequest}
                  disabled={seatRequestSubmitting}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {seatRequestSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
                  {seatRequestSubmitting ? 'Submitting…' : 'Submit Request'}
                </button>
              </div>
            </div>

            {seatRequests.length > 0 ? (
              <div className="space-y-2">
                <h3 className="text-sm font-semibold text-foreground">Recent Seat Requests</h3>
                <ul className="space-y-1 text-xs text-muted-foreground">
                  {seatRequests
                    .slice(-3)
                    .reverse()
                    .map((request, index) => {
                      const requesterSource = [request.requester_email, request.requested_by].find(
                        (value) => value && value.trim().length > 0
                      );
                      const label = withFallback(requesterSource ?? null, 'Unknown requester');
                      const requestedAt = request.requested_at ? formatDate(request.requested_at) : 'Unknown time';
                      const seatDelta = typeof request.additional_seats === 'number'
                        ? request.additional_seats
                        : typeof request.seats === 'number'
                          ? request.seats
                          : null;
                      const seats = seatDelta === null
                        ? 'Seat change unspecified'
                        : seatDelta > 0
                          ? `+${seatDelta} seats`
                          : seatDelta === 0
                            ? 'No change'
                            : `${seatDelta} seats`;
                      const newLimit = typeof request.new_limit === 'number' ? ` · New limit ${request.new_limit}` : '';
                      return (
                        <li
                          key={`${request.requested_at}-${index}`}
                          className="flex items-start justify-between gap-4 rounded border border-border/10 bg-muted/10 px-3 py-2"
                        >
                          <div>
                            <span className="font-medium text-foreground">{label}</span>
                            <span className="ml-2 text-muted-foreground">
                              requested {seats}
                              {newLimit}
                            </span>
                            {request.notes && <p className="mt-1 text-muted-foreground">{request.notes}</p>}
                          </div>
                          <span className="text-muted-foreground whitespace-nowrap">{requestedAt}</span>
                        </li>
                      );
                    })}
                </ul>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <AlertCircle className="w-4 h-4" />
                No seat upgrade requests submitted yet.
              </div>
            )}
          </GlassCard>
        )}
        {activeTab === 'Settings' && (
          <div className="space-y-4">
            <GlassCard className="p-6 space-y-4">
              <div className="flex items-center gap-3">
                <ShieldCheck className="w-5 h-5 text-primary" />
                <div>
                  <h2 className="text-lg font-semibold text-foreground">Organization Settings</h2>
                  <p className="text-sm text-muted-foreground">
                    Reference values required for SSO, subdomain routing, and company portal access.
                  </p>
                </div>
              </div>
              <dl className="grid gap-4 md:grid-cols-2 text-sm">
                <div>
                  <dt className="text-muted-foreground">Organization Name</dt>
                  <dd className="font-medium text-foreground">{profile.name}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Portal Slug</dt>
                  <dd className="font-mono text-xs text-foreground">{profile.slug}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Primary Domain</dt>
                  <dd className="text-foreground">{profile.domain ?? 'Not configured'}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Tenant Identifier</dt>
                  <dd className="font-mono text-xs text-foreground">{profile.tenant_id}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Admin Email</dt>
                  <dd className="text-foreground">{currentUser?.email}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Plan Tier</dt>
                  <dd className="capitalize text-foreground">{profile.subscription_tier}</dd>
                </div>
              </dl>
            </GlassCard>

            <IntegrationHealthPanel
              entries={integrationEntries}
              loading={integrationLoading}
              onRefresh={loadIntegrationStatus}
              formatDate={formatDate}
            />
          </div>
        )}
      </div>
    </div>
  );
}
