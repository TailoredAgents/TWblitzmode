'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import DashboardOverview from '../../components/DashboardOverview';
import ApprovalQueue from '../../components/ApprovalQueue';
import ProspectsView from '../../components/ProspectsView';
import CommunicationHub from '../../components/CommunicationHub';
import AutonomousWorkflows from '../../components/AutonomousWorkflows';
import CustomPromptInterface from '../../components/CustomPromptInterface';
import Settings from '../../components/Settings';
import GlassCard from '../../components/ui/GlassCard';
import KeyboardShortcutsModal from '../../components/ui/KeyboardShortcutsModal';
import { DashboardSkeleton } from '../../components/ui/LoadingSkeleton';
import { useToastActions } from '../../components/ui/ToastContainer';
import { useGlobalShortcuts } from '../../hooks/useKeyboardShortcuts';
import { useFocusVisible } from '../../hooks/useAccessibility';
import Sidebar from '../../components/Sidebar';
import webSocketService from '../../services/websocket';
import type { User } from '../../types';
import { agentLogger, logNavigation, logUIEvent } from '../../services/agentLogger';
import MasterGamePlanOverview from '../../components/MasterGamePlanOverview';
import { useI18n } from '../../contexts/I18nContext';
import { apiService } from '../../services/api';
import { clearAccessToken, getAccessToken } from '../../lib/authToken';

type ApprovalSocketPayload = {
  tenant_id?: number | string;
  action?: string;
};

type ApprovalSocketMessage = {
  approval?: ApprovalSocketPayload;
  data?: ApprovalSocketPayload;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const extractApprovalPayload = (message: unknown): ApprovalSocketPayload | null => {
  if (!isRecord(message)) {
    return null;
  }

  const envelope = message as ApprovalSocketMessage;
  const candidate = envelope.approval ?? envelope.data ?? message;
  if (!isRecord(candidate)) {
    return null;
  }

  const { tenant_id, action } = candidate;
  const payload: ApprovalSocketPayload = {};
  if (typeof tenant_id === 'string' || typeof tenant_id === 'number') {
    payload.tenant_id = tenant_id;
  }
  if (typeof action === 'string') {
    payload.action = action;
  }
  return payload;
};

const formatActionLabel = (action?: string): string => {
  if (!action) {
    return 'Approval';
  }

  return action
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
};

const normalizeOpaqueId = (value: unknown): string | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value.toString();
  }
  return null;
};

export default function DashboardPage() {
  const router = useRouter();
  const [activeView, setActiveView] = useState('dashboard');
  const [user, setUser] = useState<User | null>(null);
  const [pendingApprovalCount, setPendingApprovalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [showKeyboardShortcuts, setShowKeyboardShortcuts] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [featureFlags, setFeatureFlags] = useState<Record<string, boolean>>({});
  const [authReady, setAuthReady] = useState(false);
  const [autopilotMode, setAutopilotMode] = useState<'safe' | 'full'>('safe');
  const { success, error } = useToastActions();
  const { t } = useI18n();

  // Initialize accessibility features
  useFocusVisible();

  // Set up global keyboard shortcuts
  const shortcuts = useGlobalShortcuts(
    (view: string) => {
      setActiveView(view);
    },
    () => {
      setShowKeyboardShortcuts(true);
    }
  );

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const bootstrapAuth = async () => {
      try {
        if (getAccessToken()) {
          setAuthReady(true);
          return;
        }

        const refreshed = await apiService.refreshAccessToken();
        if (refreshed) {
          setAuthReady(true);
          return;
        }

        setLoading(false);
        router.replace('/login');
      } catch (error) {
        console.warn('Failed to bootstrap dashboard session', error);
        setLoading(false);
        router.replace('/login');
      }
    };

    void bootstrapAuth();
  }, [router]);

  useEffect(() => {
    const loadUserPreferences = async () => {
      if (typeof window === 'undefined' || !authReady) {
        return;
      }

      try {
        // Check sessionStorage for immediate redirect (backwards compatibility)
        const legacyPreferredView = window.sessionStorage.getItem('preferredDashboardView');
        if (legacyPreferredView) {
          if (legacyPreferredView === 'settings-cookie-jar') {
            setActiveView('settings');
          } else {
            setActiveView(legacyPreferredView);
          }
          window.sessionStorage.removeItem('preferredDashboardView');

          // Save to persistent preferences
          await apiService.setUserPreference('preferredDashboardView', legacyPreferredView);
          return;
        }

        // Load persistent preferences
        const preferencesResponse = await apiService.getUserPreferences();
        const preferredView = preferencesResponse.data?.preferredDashboardView;
        if (typeof preferredView === 'string' && preferredView.length > 0) {
          if (preferredView === 'settings-cookie-jar') {
            setActiveView('settings');
          } else {
            setActiveView(preferredView);
          }
        }
      } catch (error) {
        console.warn('Failed to load user preferences:', error);
      }
    };

    loadUserPreferences();
  }, [authReady]);

  const organizationOpaqueId = useMemo(
    () => normalizeOpaqueId(user?.organization?.id),
    [user?.organization?.id]
  );

  const tenantOpaqueId = useMemo(
    () => normalizeOpaqueId(user?.tenant_id),
    [user?.tenant_id]
  );

  const userOpaqueId = useMemo(() => normalizeOpaqueId(user?.id), [user?.id]);

  const resolvedOrganizationId = useMemo(
    () => organizationOpaqueId ?? tenantOpaqueId ?? null,
    [organizationOpaqueId, tenantOpaqueId]
  );

  const resolvedTenantId = useMemo(
    () => tenantOpaqueId ?? organizationOpaqueId ?? null,
    [tenantOpaqueId, organizationOpaqueId]
  );

  const organizationIdForProspects = useMemo(
    () => organizationOpaqueId ?? resolvedTenantId,
    [organizationOpaqueId, resolvedTenantId]
  );

  const connectionTenant = useMemo(
    () => resolvedTenantId ?? organizationIdForProspects ?? null,
    [resolvedTenantId, organizationIdForProspects]
  );

  const connectionUser = userOpaqueId ?? null;

  const hasOrganizationContext = Boolean(connectionTenant);
  const hasUserContext = Boolean(connectionUser);

  const initializeDashboard = useCallback(async () => {
    try {
      const userResponse = await apiService.getCurrentUser();
      const fetchedUser = userResponse.data;

      if (fetchedUser) {
        setUser(fetchedUser);
      }

      const fetchedOrganizationKey = normalizeOpaqueId(fetchedUser?.organization?.id);
      const fetchedTenantKey = normalizeOpaqueId(fetchedUser?.tenant_id);

      const featureFlagsPromise = apiService
        .getFeatureFlags()
        .catch((err) => {
          console.warn('Feature flags endpoint unavailable:', err);
          return null;
        });
      let approvalsTotal = 0;

      const approvalsTenantId = fetchedTenantKey ?? fetchedOrganizationKey;

      if (approvalsTenantId) {
        try {
          const approvalsResponse = await apiService.getApprovalRequests({
            tenantId: approvalsTenantId,
            status: 'pending',
            page: 1,
            limit: 1,
          });
          approvalsTotal =
            approvalsResponse.pagination?.total || approvalsResponse.data.length;
        } catch (approvalsError) {
          console.warn('Approvals endpoint unavailable:', approvalsError);
        }
      }
      setPendingApprovalCount(approvalsTotal);

      const featureFlagEnvelope = await featureFlagsPromise;
      setFeatureFlags(featureFlagEnvelope?.data?.flags ?? {});

      if (fetchedUser?.id) {
        const organizationContext = fetchedOrganizationKey ?? approvalsTenantId ?? null;

        if (organizationContext) {
          agentLogger.setUserContext(fetchedUser.id.toString(), organizationContext);

          await logUIEvent('dashboard_init', 'DashboardPage', {
            user_id: fetchedUser.id.toString(),
            organization_id: organizationContext,
            pending_approvals: approvalsTotal,
          });

          webSocketService.joinOrganizationRoom(organizationContext);
        } else {
          await logUIEvent('dashboard_init', 'DashboardPage', {
            user_id: fetchedUser.id.toString(),
            organization_id: null,
            pending_approvals: approvalsTotal,
          });
        }
      }
    } catch (err) {
      console.error('Failed to initialize dashboard:', err);
      error(
        t('dashboard.errors.loadDashboardData'),
        t('dashboard.errors.loadDashboardHint'),
      );
    } finally {
      setLoading(false);
    }
  }, [error, t]);

  useEffect(() => {
    if (!authReady) {
      return;
    }
    void initializeDashboard();
  }, [authReady, initializeDashboard]);

  const handleNewApproval = useCallback((message: unknown) => {
    const payload = extractApprovalPayload(message);
    if (!payload) {
      return;
    }

    const orgId = organizationIdForProspects;
    if (!orgId) {
      return;
    }

    if (payload.tenant_id && String(payload.tenant_id) !== String(orgId)) {
      return;
    }

    setPendingApprovalCount((prev) => prev + 1);
    const actionLabel = formatActionLabel(payload.action);
    success(`${t('dashboard.notifications.newApproval')} ${actionLabel}`, t('dashboard.notifications.reviewHint'), {
      action: {
        label: t('dashboard.notifications.review'),
        onClick: () => setActiveView('approvals')
      }
    });
  }, [organizationIdForProspects, success, t, setActiveView]);

  const handleApprovalUpdate = useCallback((message: unknown) => {
    const update = extractApprovalPayload(message);
    if (!update) {
      return;
    }

    const orgId = organizationIdForProspects;
    if (!orgId) {
      return;
    }

    if (update.tenant_id && String(update.tenant_id) !== String(orgId)) {
      return;
    }

    setPendingApprovalCount((prev) => Math.max(0, prev - 1));
  }, [organizationIdForProspects]);

  useEffect(() => {
    if (!user || !connectionTenant || !connectionUser) {
      return;
    }

    webSocketService.setUserContext(connectionUser, connectionTenant);
    webSocketService.connect({ tenantId: connectionTenant, userId: connectionUser });
    webSocketService.joinOrganizationRoom(connectionTenant);
    webSocketService.joinApprovalRoom(connectionTenant);

    webSocketService.on('approval_request', handleNewApproval);
    webSocketService.on('approval_decision', handleApprovalUpdate);

    return () => {
      webSocketService.off('approval_request', handleNewApproval);
      webSocketService.off('approval_decision', handleApprovalUpdate);
      webSocketService.leaveApprovalRoom(connectionTenant);
      webSocketService.disconnect();
    };
  }, [user, connectionTenant, connectionUser, handleNewApproval, handleApprovalUpdate]);

  const handleNavigation = async (view: string) => {
    setActiveView(view);
    await logNavigation('dashboard', view);

    // Save preference change to persistent storage
    try {
      await apiService.setUserPreference('lastActiveView', view);
    } catch (error) {
      console.warn('Failed to save view preference:', error);
    }
  };

  const handleAutopilotToggle = useCallback(() => {
    setAutopilotMode((prev) => {
      const next = prev === 'safe' ? 'full' : 'safe';
      success(
        t(
          'dashboard.autopilotToast',
          next === 'full'
            ? 'Autopilot switched to Full mode. Link will run proactively after confirmations.'
            : 'Autopilot switched to Safe mode. Link will confirm before running tools.',
        ),
      );
      void logUIEvent('autopilot_toggle', 'dashboard', { nextMode: next });
      return next;
    });
  }, [success, t]);

  const handleSwitchAccount = useCallback(async () => {
    try {
      await logUIEvent('switch-account', 'dashboard', {
        userId: user?.id ?? null,
        organizationId: resolvedOrganizationId ?? null,
      });
    } catch (eventError) {
      console.warn('Failed to log switch account action', eventError);
    }

    try {
      await apiService.logout();
    } catch (logoutError) {
      console.warn('Switch account logout failed', logoutError);
    } finally {
      clearAccessToken();
      if (typeof window !== 'undefined') {
        try {
          window.sessionStorage.removeItem('preferredDashboardView');
          window.sessionStorage.removeItem('preferredSettingsTab');
        } catch (storageError) {
          console.warn('Failed to clear session storage during account switch', storageError);
        }
      }
      router.replace('/login?switch=1');
    }
  }, [router, resolvedOrganizationId, user?.id]);

  const renderOrganizationRequired = (
    factory: () => React.ReactNode,
    options: { requireUser?: boolean } = {},
  ) => {
    const { requireUser = false } = options;

    if (!hasOrganizationContext || (requireUser && !hasUserContext)) {
      return (
        <GlassCard className="p-6">
          <div className="space-y-2">
            <h2 className="text-lg font-semibold text-foreground border-l-2 border-primary/30 pl-3">Complete your organization setup</h2>
            <p className="text-sm text-muted-foreground">
              We couldn&apos;t determine your organization context. Ask an administrator to assign you to an organization or
              refresh once setup is complete.
            </p>
          </div>
        </GlassCard>
      );
    }

    return factory();
  };

  const renderActiveView = () => {
    switch (activeView) {
      case 'dashboard':
        return renderOrganizationRequired(() => {
          if (!resolvedOrganizationId || !connectionUser) {
            return null;
          }
          return <DashboardOverview organizationId={resolvedOrganizationId} userId={connectionUser} />;
        }, { requireUser: true });
      case 'approvals':
        return renderOrganizationRequired(() => {
          const contextId = organizationIdForProspects ?? connectionTenant;
          if (!contextId) {
            return null;
          }
          return <ApprovalQueue organizationId={contextId} currentUser={user} />;
        });
      case 'prospects':
        return renderOrganizationRequired(() => {
          const contextId = organizationIdForProspects ?? connectionTenant;
          if (!contextId) {
            return null;
          }
          return <ProspectsView organizationId={contextId} />;
        });
      case 'communication-hub':
        return renderOrganizationRequired(() => {
          if (!resolvedOrganizationId || !connectionTenant || !connectionUser) {
            return null;
          }
          const currentUserContext = connectionUser
            ? {
                id: connectionUser,
                tenant_id: connectionTenant,
                organization_id: resolvedOrganizationId,
              }
            : undefined;
          const currentUserProps = currentUserContext ? { currentUser: currentUserContext } : {};
          return (
            <CommunicationHub
              organizationId={resolvedOrganizationId}
              tenantId={connectionTenant}
              userId={connectionUser}
              {...currentUserProps}
            />
          );
        }, { requireUser: true });
      case 'workflows':
        return renderOrganizationRequired(() => {
          if (!resolvedOrganizationId || !connectionTenant) {
            return null;
          }
          return <AutonomousWorkflows organizationId={resolvedOrganizationId} tenantId={connectionTenant} />;
        });
      case 'ai-prompting':
        return renderOrganizationRequired(() => {
          if (!resolvedOrganizationId) {
            return null;
          }
          return <CustomPromptInterface organizationId={resolvedOrganizationId} />;
        });
      case 'master-game-plan':
        return renderOrganizationRequired(() => {
          if (!resolvedOrganizationId || !connectionTenant) {
            return null;
          }
          return (
            <MasterGamePlanOverview
              organizationId={resolvedOrganizationId}
              tenantId={connectionTenant}
              userRole={user?.role === 'admin' ? 'admin' : 'user'}
            />
          );
        });
      case 'settings':
        return <Settings />;
      case 'emails':
        return (
          <div className="p-8">
            <GlassCard className="p-6">
              <div className="space-y-3">
                <h2 className="text-xl font-semibold text-foreground border-l-2 border-primary/30 pl-3">Email Campaigns</h2>
                <p className="text-sm text-muted-foreground">
                  Access campaign templates, deliverability reports, and queue warm-up diagnostics from the dedicated Email Console.
                </p>
                <p className="text-sm text-muted-foreground">
                  Use the Email Console link in the sidebar to jump into the full email orchestration experience.
                </p>
              </div>
            </GlassCard>
          </div>
        );
      case 'integrations':
        return (
          <div className="p-8">
            <GlassCard className="p-6">
              <div className="space-y-3">
                <h2 className="text-xl font-semibold text-foreground border-l-2 border-primary/30 pl-3">Integrations Overview</h2>
                <p className="text-sm text-muted-foreground">
                  Apify Saswave mutual discovery and SendGrid email delivery are required for every tenant to unlock Link automations.
                </p>
                <p className="text-sm text-muted-foreground">
                  PhantomBuster is optional and only executes after users approve a secondary enrichment run—enter those credentials if you plan to use the fallback.
                </p>
                <p className="text-sm text-muted-foreground">
                  Visit the admin console to configure team-wide defaults or user-level overrides.
                </p>
              </div>
            </GlassCard>
          </div>
        );
      default:
        return renderOrganizationRequired(() => {
          if (!resolvedOrganizationId || !connectionUser) {
            return null;
          }
          return <DashboardOverview organizationId={resolvedOrganizationId} userId={connectionUser} />;
        }, { requireUser: true });
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen bg-background">
        <DashboardSkeleton />
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden dashboard-theme">
      <Sidebar
        activeView={activeView}
        onViewChange={handleNavigation}
        user={user}
        pendingApprovals={pendingApprovalCount}
        sidebarOpen={sidebarOpen}
        setSidebarOpen={setSidebarOpen}
        featureFlags={featureFlags}
      />

      <main className="flex-1 overflow-y-auto ai-surface dashboard-theme">
        <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-lg border-b border-border/20">
          <div className="flex items-center justify-between px-6 py-4">
            <div className="flex items-center gap-3">
              <button
                type="button"
                data-testid="switch-account-button"
                onClick={handleSwitchAccount}
                className="inline-flex items-center gap-2 rounded-lg border border-border/40 bg-background/60 px-3 py-2 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                aria-label={t('dashboard.switchAccount', 'Switch account')}
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                <span>{t('dashboard.switchAccount', 'Switch account')}</span>
              </button>
              <button
                type="button"
                className="lg:hidden inline-flex items-center justify-center rounded-lg border border-border/40 bg-background/60 px-3 py-2 text-sm font-medium text-foreground shadow-sm hover:bg-muted/50 transition-colors"
                onClick={() => setSidebarOpen((prev) => !prev)}
              >
                <span className="sr-only">Open sidebar</span>
                <svg className="h-5 w-5" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path
                    d="M3 5h14M3 10h14M3 15h10"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              <div>
                <p className="text-xs text-muted-foreground">Welcome back</p>
                <h1 className="text-lg font-semibold text-foreground tracking-tight">
                  {user?.name ? `${t('dashboard.greetings.hello')}, ${user.name}` : t('dashboard.title')}
                </h1>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="hidden md:flex flex-col items-end pr-3 border-r border-border/30">
                <span className="text-xs text-muted-foreground">
                  {t('dashboard.autopilotLabel', 'Autopilot')}
                </span>
                <button
                  type="button"
                  className="mt-1 inline-flex items-center gap-1 rounded-full border border-border/40 bg-background/50 px-3 py-1 text-xs font-medium text-foreground shadow-sm hover:bg-muted/40 transition-colors"
                  onClick={handleAutopilotToggle}
                >
                  {autopilotMode === 'full'
                    ? t('dashboard.autopilotFull', 'Full (agentic)')
                    : t('dashboard.autopilotSafe', 'Safe (confirm)')}
                </button>
              </div>
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-lg border border-border/40 bg-background/60 px-3 py-2 text-sm font-medium text-foreground shadow-sm hover:bg-muted/50 transition-colors"
                onClick={() => setShowKeyboardShortcuts(true)}
              >
                <span className="text-xs text-muted-foreground">⌘</span>
                <span>{t('dashboard.shortcutsLabel')}</span>
              </button>
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-sm font-medium text-primary shadow-sm hover:bg-primary/20 transition-colors"
                onClick={() => handleNavigation('approvals')}
              >
                <span>{t('dashboard.quickActions.reviewApprovals')}</span>
                <span className="rounded-full bg-primary/20 px-2 py-0.5 text-xs font-semibold text-primary">
                  {pendingApprovalCount}
                </span>
              </button>
            </div>
          </div>
        </header>

        <section className="p-6 space-y-6">{renderActiveView()}</section>
      </main>

      <KeyboardShortcutsModal
        isOpen={showKeyboardShortcuts}
        onClose={() => setShowKeyboardShortcuts(false)}
        shortcuts={shortcuts}
      />
    </div>
  );
}
