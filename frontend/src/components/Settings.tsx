'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import axios from 'axios';
import {
  Settings as SettingsIcon,
  User as UserIcon,
  Bell,
  Shield,
  Database,
  Save,
  RotateCcw,
  RefreshCw,
  Key,
  KeyRound,
  Monitor,
  Loader2,
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  Eye,
  EyeOff,
  Cookie as CookieIcon,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import GlassCard from './ui/GlassCard';
import { useToastActions } from './ui/ToastContainer';
import { apiService } from '../services/api';
import { clearAccessToken } from '../lib/authToken';
import webSocketService from '../services/websocket';
import type {
  APIResponse,
  CookieStatus,
  CredentialStatus,
  ProviderHealthStatus,
  User as AppUser,
} from '../types';
import { useI18n } from '../contexts/I18nContext';
import { isAdminRole, normalizeRole } from '../lib/roles';

interface UserSettings {
  id: number;
  email: string;
  name: string;
  role: string;
  timezone: string;
  language: string;
  theme: 'light' | 'dark' | 'auto';
  notifications: {
    email: boolean;
    browser: boolean;
    workflows: boolean;
    approvals: boolean;
    system: boolean;
  };
}

interface SystemSettings {
  auto_approval_threshold: number;
  max_concurrent_workflows: number;
  workflow_timeout_minutes: number;
  rate_limit_per_minute: number;
  debug_mode: boolean;
  audit_logging: boolean;
  data_retention_days: number;
  backup_frequency_hours: number;
}

interface SecuritySettings {
  session_timeout_minutes: number;
  require_2fa: boolean;
  password_expiry_days: number;
  max_failed_attempts: number;
  ip_whitelist_enabled: boolean;
  cors_origins: string[];
}

interface APICredentials {
  openai_api_key: string;
  apify_api_token: string;
  cufinder_api_key: string;
  sendgrid_api_key: string;
  phantombuster_api_key: string;
  linkedin_li_at: string;
}

type ApiCredentialKey = keyof APICredentials;

type SettingsSection = 'user' | 'system' | 'security' | 'credentials';

type UserSettingsPayload = Partial<UserSettings> & {
  id?: number | string;
  user_id?: number | string;
  notifications?: Partial<UserSettings['notifications']>;
};

type SystemSettingsPayload = Partial<SystemSettings>;
type SecuritySettingsPayload = Partial<SecuritySettings>;
type CredentialsPayload = {
  secrets?: Record<ApiCredentialKey, CredentialStatus>;
} & Record<string, unknown>;

type CookieUpdatePayload = Partial<CookieStatus> & {
  cookie?: Partial<CookieStatus>;
  organizationId?: number | string;
  organization_id?: number | string;
  user_id?: number | string;
};

const API_CREDENTIAL_KEYS: ApiCredentialKey[] = [
  'openai_api_key',
  'apify_api_token',
  'cufinder_api_key',
  'sendgrid_api_key',
  'phantombuster_api_key',
  'linkedin_li_at',
];

const INITIAL_USER_SETTINGS: UserSettings = {
  id: 0,
  email: '',
  name: '',
  role: '',
  timezone: 'UTC',
  language: 'en',
  theme: 'auto',
  notifications: {
    email: false,
    browser: false,
    workflows: false,
    approvals: false,
    system: false,
  },
};

const INITIAL_SYSTEM_SETTINGS: SystemSettings = {
  auto_approval_threshold: 0,
  max_concurrent_workflows: 0,
  workflow_timeout_minutes: 0,
  rate_limit_per_minute: 0,
  debug_mode: false,
  audit_logging: false,
  data_retention_days: 0,
  backup_frequency_hours: 0,
};

const INITIAL_SECURITY_SETTINGS: SecuritySettings = {
  session_timeout_minutes: 0,
  require_2fa: false,
  password_expiry_days: 0,
  max_failed_attempts: 0,
  ip_whitelist_enabled: false,
  cors_origins: [],
};

const INITIAL_API_CREDENTIAL_ENTRIES: Array<[ApiCredentialKey, string]> = [
  ['openai_api_key', ''],
  ['apify_api_token', ''],
  ['cufinder_api_key', ''],
  ['sendgrid_api_key', ''],
  ['phantombuster_api_key', ''],
  ['linkedin_li_at', ''],
];

export default function Settings() {
  const { t } = useI18n();
  const translate = useCallback(
    (key: string, fallback: string) => t(`settings.${key}`, fallback),
    [t],
  );
  const router = useRouter();
  const [activeTab, setActiveTab] = useState('user');
  const [userSettings, setUserSettings] = useState<UserSettings>(INITIAL_USER_SETTINGS);

  const [systemSettings, setSystemSettings] = useState<SystemSettings>(INITIAL_SYSTEM_SETTINGS);

  const [securitySettings, setSecuritySettings] = useState<SecuritySettings>(INITIAL_SECURITY_SETTINGS);

  const [apiCredentials, setApiCredentials] = useState<Map<ApiCredentialKey, string>>(
    () => new Map(INITIAL_API_CREDENTIAL_ENTRIES)
  );
  const [apiCredentialStatus, setApiCredentialStatus] = useState<Map<ApiCredentialKey, CredentialStatus>>(
    () => new Map()
  );

  const [showApiKeys, setShowApiKeys] = useState<Map<ApiCredentialKey, boolean>>(() => new Map());
  const [loading, setLoading] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [currentUser, setCurrentUser] = useState<AppUser | null>(null);
  const [cookieOrgId, setCookieOrgId] = useState<number | null>(null);
  const [cookieStatus, setCookieStatus] = useState<CookieStatus | null>(null);
  const [cookieForm, setCookieForm] = useState<{ li_at: string; jsessionid?: string; user_agent?: string }>({
    li_at: '',
    jsessionid: '',
    user_agent: '',
  });
  const [cookieLoading, setCookieLoading] = useState(false);
  const [providerHealth, setProviderHealth] = useState<Record<string, ProviderHealthStatus>>({});
  const [providerHealthLoading, setProviderHealthLoading] = useState(false);
  const providerHealthMap = useMemo(
    () => new Map<string, ProviderHealthStatus>(Object.entries(providerHealth ?? {})),
    [providerHealth]
  );
  const [passwordResetLoading, setPasswordResetLoading] = useState(false);
  const [passwordResetFeedback, setPasswordResetFeedback] = useState<{ kind: 'success' | 'error'; message: string } | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { success, error } = useToastActions();

  const isAdminUser = useCallback((user?: AppUser | null) => isAdminRole(user?.role), []);

  const extractOrganizationId = useCallback((user?: AppUser | null): number | null => {
    if (!user) {
      return null;
    }

    const orgIdCandidate = user.organization?.id ?? user.tenant_id ?? null;
    if (typeof orgIdCandidate === 'number') {
      return orgIdCandidate;
    }
    if (typeof orgIdCandidate === 'string' && orgIdCandidate.trim().length > 0) {
      const parsed = Number(orgIdCandidate);
      return Number.isNaN(parsed) ? null : parsed;
    }
    return null;
  }, []);

  const canManageSettings = useMemo(() => isAdminUser(currentUser), [isAdminUser, currentUser]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const preferredTab = window.sessionStorage.getItem('preferredSettingsTab');
    if (preferredTab) {
      setActiveTab(preferredTab);
      window.sessionStorage.removeItem('preferredSettingsTab');
    }
  }, []);

  const getCookieStatusClasses = (status: string): string => {
    switch (status) {
      case 'pending':
        return 'bg-blue-500/20 text-blue-600';
      case 'valid':
        return 'bg-emerald-500/20 text-emerald-600';
      case 'invalid':
        return 'bg-rose-500/20 text-rose-600';
      case 'expired':
        return 'bg-amber-500/20 text-amber-600';
      case 'missing':
      default:
        return 'bg-slate-500/20 text-slate-600';
    }
  };

  const formatTimestamp = (value?: string | null): string => {
    if (!value) {
      return t('shared.never', 'Never');
    }
    try {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return value;
      }
      return date.toLocaleString();
    } catch {
      return value ?? t('shared.never', 'Never');
    }
  };

  const loadSettings = useCallback(async (userContext?: AppUser | null) => {
    const contextUser = userContext ?? currentUser;
    const shouldFetchAdminData = isAdminUser(contextUser);
    const requestEntries: Array<{ key: SettingsSection; request: Promise<APIResponse<unknown>> }> = [
      { key: 'user', request: apiService.get('/api/settings/user') },
    ];

    if (shouldFetchAdminData) {
      requestEntries.push({ key: 'system', request: apiService.get('/api/settings/system') });
      requestEntries.push({ key: 'security', request: apiService.get('/api/settings/security') });
      requestEntries.push({ key: 'credentials', request: apiService.get('/api/settings/credentials') });
    }

    try {
      setLoading(true);
      const results = await Promise.all(
        requestEntries.map(async ({ key, request }) => {
          try {
            const value = await request;
            return { status: 'fulfilled' as const, key, value };
          } catch (reason) {
            return { status: 'rejected' as const, key, reason };
          }
        })
      );
      let userRequestFailed = false;
      let adminPermsDenied = false;

      results.forEach((result) => {
        if (result.status !== 'fulfilled') {
          if (result.key === 'user') {
            userRequestFailed = true;
          }
          if (
            result.key !== 'user' &&
            axios.isAxiosError(result.reason) &&
            result.reason.response?.status === 403
          ) {
            adminPermsDenied = true;
          }
          console.error(`Failed to load ${result.key} settings:`, result.reason);
          return;
        }

        const rawData = result.value?.data ?? result.value;
        if (!rawData || typeof rawData !== 'object') {
          return;
        }

        if (result.key === 'user') {
          const payload = rawData as UserSettingsPayload;
          const normalized: UserSettings = {
            ...INITIAL_USER_SETTINGS,
            ...payload,
            id: Number(payload.id ?? payload.user_id ?? INITIAL_USER_SETTINGS.id),
            notifications: {
              ...INITIAL_USER_SETTINGS.notifications,
              ...(payload.notifications ?? {}),
            },
          };
          setUserSettings(normalized);
        } else if (result.key === 'system') {
          const payload = rawData as SystemSettingsPayload;
          setSystemSettings({
            ...INITIAL_SYSTEM_SETTINGS,
            ...(payload ?? {}),
          });
        } else if (result.key === 'security') {
          const payload = rawData as SecuritySettingsPayload;
          setSecuritySettings({
            ...INITIAL_SECURITY_SETTINGS,
            ...(payload ?? {}),
            cors_origins: Array.isArray(payload?.cors_origins)
              ? [...payload.cors_origins]
              : [...INITIAL_SECURITY_SETTINGS.cors_origins],
          });
        } else if (result.key === 'credentials') {
          const payload = rawData as CredentialsPayload;
          const secretsRecord = payload.secrets ?? {};
          const secretEntries = Object.entries(secretsRecord).filter(
            (entry): entry is [ApiCredentialKey, CredentialStatus] => API_CREDENTIAL_KEYS.includes(entry[0] as ApiCredentialKey)
          );
          const secretStatuses = new Map<ApiCredentialKey, CredentialStatus>(secretEntries);
          const statusEntries = API_CREDENTIAL_KEYS.flatMap((credentialKey) => {
            const status = secretStatuses.get(credentialKey);
            return status ? ([[credentialKey, status]] as Array<[ApiCredentialKey, CredentialStatus]>) : [];
          });
          setApiCredentialStatus(new Map(statusEntries));
          setApiCredentials(new Map(INITIAL_API_CREDENTIAL_ENTRIES));
          setShowApiKeys(new Map());
        }
      });

      if (!shouldFetchAdminData) {
        setSystemSettings({ ...INITIAL_SYSTEM_SETTINGS });
        setSecuritySettings({
          ...INITIAL_SECURITY_SETTINGS,
          cors_origins: [...INITIAL_SECURITY_SETTINGS.cors_origins],
        });
        setApiCredentials(new Map(INITIAL_API_CREDENTIAL_ENTRIES));
        setApiCredentialStatus(new Map());
        setShowApiKeys(new Map());
      }

      if (userRequestFailed) {
        error(translate('errors.loadSettings', 'Failed to load settings'));
      } else {
        setHasChanges(false);
      }

      if (adminPermsDenied) {
        error(
          translate('errors.permissionDenied', 'Insufficient permissions'),
          translate('errors.permissionDeniedHint', 'Contact an administrator to modify organization-wide settings.')
        );
      }
    } catch (err) {
      console.error('Failed to load settings:', err);
      error(translate('errors.loadSettings', 'Failed to load settings'));
    } finally {
      setLoading(false);
    }
  }, [currentUser, error, translate, isAdminUser]);

  const loadUserContext = useCallback(async () => {
    let resolvedUser: AppUser | null = null;
    try {
      const response = await apiService.getCurrentUser();
      const userData = response.data;
      if (userData) {
        resolvedUser = userData;
        setCurrentUser(userData);
        const derivedOrgId = extractOrganizationId(userData);
        if (derivedOrgId) {
          setCookieOrgId(Number(derivedOrgId));
        }
        if (derivedOrgId && userData?.id !== undefined) {
          webSocketService.connect({ tenantId: derivedOrgId, userId: userData.id });
        }
      }
    } catch (err) {
      console.error('Failed to load user context:', err);
    }
    await loadSettings(resolvedUser);
  }, [loadSettings, extractOrganizationId]);

  const fetchCookieStatus = useCallback(async (orgId: number) => {
    try {
      const response = await apiService.getCookieJarStatus(orgId);
      setCookieStatus(response.data ?? null);
    } catch (err) {
      console.error('Failed to load cookie jar status:', err);
    }
  }, []);

  useEffect(() => {
    void loadUserContext();
  }, [loadUserContext]);

  useEffect(() => {
    if (!cookieOrgId) {
      return () => undefined;
    }

    webSocketService.joinCookieRoom(cookieOrgId);
    return () => {
      webSocketService.leaveCookieRoom(cookieOrgId);
    };
  }, [cookieOrgId]);

  useEffect(() => {
    if (cookieOrgId) {
      void fetchCookieStatus(cookieOrgId);
    }
  }, [cookieOrgId, fetchCookieStatus]);

  useEffect(() => {
    const handleCookieUpdate = (payload: unknown) => {
      if (!payload || typeof payload !== 'object') {
        return;
      }

      const scopedPayload = payload as CookieUpdatePayload & { cookie?: CookieUpdatePayload };
      const update = (scopedPayload.cookie ?? scopedPayload) as CookieUpdatePayload | undefined;
      if (!update) {
        return;
      }

      const organizationCandidate = update.organization_id ?? update.organizationId ?? cookieOrgId;
      const matchesOrg = cookieOrgId
        ? Number(organizationCandidate ?? cookieOrgId) === Number(cookieOrgId)
        : true;
      if (!matchesOrg) {
        return;
      }

      const updateUserId = update.user_id;
      if (updateUserId !== undefined && currentUser?.id !== undefined) {
        if (Number(updateUserId) !== Number(currentUser.id)) {
          return;
        }
      }

      setCookieStatus((prev) => {
        const base: CookieStatus = prev ?? { status: 'pending' };
        return { ...base, ...update };
      });
    };

    webSocketService.on('cookie_update', handleCookieUpdate);

    return () => {
      webSocketService.off('cookie_update', handleCookieUpdate);
    };
  }, [cookieOrgId, currentUser?.id]);

  useEffect(() => {
    if (!canManageSettings || activeTab !== 'api') {
      return;
    }

    let cancelled = false;
    setProviderHealthLoading(true);
    void apiService
      .getProviderHealth()
      .then((response) => {
        if (!cancelled) {
          setProviderHealth(response.data ?? {});
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProviderHealth({});
          error(
            translate(
              'api.providers.loadError',
              'Unable to load provider status. Please retry in a moment.',
            ),
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setProviderHealthLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [canManageSettings, activeTab, error, translate]);

  const handleSaveSettings = async () => {
    if (activeTab !== 'user' && !canManageSettings) {
      error(
        translate('errors.permissionDenied', 'You do not have permission to modify these settings'),
        translate('errors.permissionDeniedHint', 'Contact an administrator to update organization settings.'),
      );
      return;
    }

    try {
      setLoading(true);

      const savePromises: Promise<APIResponse<unknown>>[] = [];

      if (activeTab === 'user') {
        savePromises.push(apiService.put('/api/settings/user', userSettings));
      } else if (activeTab === 'system') {
        savePromises.push(apiService.put('/api/settings/system', systemSettings));
      } else if (activeTab === 'security') {
        savePromises.push(apiService.put('/api/settings/security', securitySettings));
      } else if (activeTab === 'api') {
        const credentialPayload = Object.fromEntries(apiCredentials) as Record<string, string>;
        savePromises.push(apiService.put('/api/settings/credentials', credentialPayload));
      }

      if (savePromises.length === 0) {
        setLoading(false);
        return;
      }

      await Promise.all(savePromises);
      if (activeTab === 'api') {
        await loadSettings(currentUser);
      }
      setHasChanges(false);
      success(translate('messages.saveSuccess', 'Settings saved successfully'));
    } catch (err) {
      console.error('Failed to save settings:', err);
      error(translate('errors.saveFailed', 'Failed to save settings'));
    } finally {
      setLoading(false);
    }
  };

  const handleResetToDefaults = () => {
    if (activeTab === 'user') {
      setUserSettings({
        ...userSettings,
        timezone: INITIAL_USER_SETTINGS.timezone,
        language: INITIAL_USER_SETTINGS.language,
        theme: INITIAL_USER_SETTINGS.theme,
        notifications: {
          ...INITIAL_USER_SETTINGS.notifications,
        },
      });
      setHasChanges(true);
      return;
    }

    if (!canManageSettings) {
      return;
    }

    if (activeTab === 'system') {
      setSystemSettings({ ...INITIAL_SYSTEM_SETTINGS });
      setHasChanges(true);
    } else if (activeTab === 'security') {
      setSecuritySettings({
        ...INITIAL_SECURITY_SETTINGS,
        cors_origins: [...INITIAL_SECURITY_SETTINGS.cors_origins],
      });
      setHasChanges(true);
    } else if (activeTab === 'api') {
      setApiCredentials(new Map(INITIAL_API_CREDENTIAL_ENTRIES));
      setShowApiKeys(new Map());
      setHasChanges(true);
    }
  };

  const toggleApiKeyVisibility = (key: ApiCredentialKey) => {
    setShowApiKeys((prev) => {
      const next = new Map(prev);
      const current = next.get(key) ?? false;
      next.set(key, !current);
      return next;
    });
  };

  const handleCookieInputChange = (field: 'li_at' | 'jsessionid' | 'user_agent', value: string) => {
    setCookieForm((prev) => {
      if (field === 'li_at') {
        return { ...prev, li_at: value };
      }
      if (field === 'jsessionid') {
        return { ...prev, jsessionid: value };
      }
      return { ...prev, user_agent: value };
    });
  };

  const handleCookieJarSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canManageSettings) {
      error(
        translate('cookie.errors.permission', 'Administrator action required'),
        translate('cookie.errors.permissionHint', 'Only organization admins can upload LinkedIn cookies.'),
      );
      return;
    }
    if (!cookieOrgId) {
      error(
        translate('errors.missingOrganization', 'Organization context missing'),
        translate('errors.missingOrganizationHint', 'Please refresh the page and try again.'),
      );
      return;
    }
    if (!cookieForm.li_at.trim()) {
      error(
        translate('errors.liAtRequired', 'li_at cookie required'),
        translate('errors.liAtRequiredHint', 'Paste the LinkedIn li_at cookie to continue.'),
      );
      return;
    }

    setCookieLoading(true);
    try {
      // Import encryption utilities
      const { encryptCookies, isEncryptionSupported } = await import('../lib/encryption');

      // Check if encryption is supported
      if (!isEncryptionSupported()) {
        error(
          translate('errors.encryptionUnsupported', 'Browser encryption not supported'),
          translate('errors.encryptionUnsupportedHint', 'Please use a modern browser for secure cookie upload.'),
        );
        return;
      }

      // Encrypt cookies before transmission
      const encryptedData = await encryptCookies({
        li_at: cookieForm.li_at.trim(),
        ...(cookieForm.jsessionid?.trim() && { jsessionid: cookieForm.jsessionid.trim() }),
        ...(cookieForm.user_agent?.trim() && { user_agent: cookieForm.user_agent.trim() }),
      });

      // Send encrypted payload to backend
      const response = await apiService.uploadCookieJar(cookieOrgId, encryptedData);
      setCookieStatus(response.data ?? null);
      success(
        translate('messages.cookieUpdated', 'Cookie jar updated'),
        translate('messages.cookieUpdatedHint', 'We will validate your LinkedIn session shortly.'),
      );
    } catch (err) {
      console.error('Failed to upload cookie jar:', err);
      error(
        translate('errors.cookieUploadFailed', 'Failed to upload cookies'),
        translate('errors.cookieUploadFailedHint', 'Please verify the values and try again.'),
      );
    } finally {
      setCookieLoading(false);
    }
  };

  const handleCookieRevalidate = async () => {
    if (!cookieOrgId || !cookieStatus?.id) {
      error(translate('errors.noCookieJar', 'No cookie jar available to revalidate'));
      return;
    }
    if (!canManageSettings) {
      error(
        translate('cookie.errors.permission', 'Administrator action required'),
        translate('cookie.errors.permissionHint', 'Only organization admins can revalidate LinkedIn cookies.'),
      );
      return;
    }
    setCookieLoading(true);
    try {
      const response = await apiService.revalidateCookieJar(cookieOrgId, cookieStatus.id);
      setCookieStatus(response.data ?? null);
      success(
        translate('messages.validationRequested', 'Validation requested'),
        translate('messages.validationRequestedHint', 'We are re-checking your LinkedIn session.'),
      );
    } catch (err) {
      console.error('Failed to revalidate cookie jar:', err);
      error(translate('errors.revalidateFailed', 'Could not revalidate cookies'));
    } finally {
      setCookieLoading(false);
    }
  };

  const tabs = useMemo(() => {
    const base = [{ id: 'user', label: translate('tabs.user', 'User Preferences'), icon: UserIcon }];

    if (canManageSettings) {
      base.push(
        { id: 'system', label: translate('tabs.system', 'System Config'), icon: Database },
        { id: 'security', label: translate('tabs.security', 'Security'), icon: Shield },
        { id: 'api', label: translate('tabs.api', 'API Keys'), icon: Key },
      );
    }

    base.push({ id: 'cookie-jar', label: translate('tabs.cookieJar', 'Cookie Jar'), icon: CookieIcon });

    return base;
  }, [translate, canManageSettings]);

  useEffect(() => {
    if (!tabs.some((tab) => tab.id === activeTab)) {
      setActiveTab('user');
    }
  }, [tabs, activeTab]);

  const notificationLabels = useMemo(
    () => ({
      email: translate('user.notifications.email', 'Email notifications'),
      browser: translate('user.notifications.browser', 'Browser notifications'),
      workflows: translate('user.notifications.workflows', 'Workflow updates'),
      approvals: translate('user.notifications.approvals', 'Approval queue alerts'),
      system: translate('user.notifications.system', 'System notices'),
    }),
    [translate],
  );

  const systemOptionLabels = useMemo(
    () => ({
      debug_mode: translate('system.options.debugMode', 'Debug Mode'),
      audit_logging: translate('system.options.auditLogging', 'Audit Logging'),
    }),
    [translate],
  );

  const securityToggleLabels = useMemo(
    () => ({
      require_2fa: translate('security.requireTwoFactor', 'Require Two-Factor Authentication'),
      ip_whitelist_enabled: translate('security.enableIpWhitelist', 'Enable IP Whitelist'),
    }),
    [translate],
  );

  const apiFieldLabels = useMemo(
    () => ({
      openai_api_key: translate('api.keys.openai', 'OpenAI API Key'),
      apify_api_token: translate('api.keys.apify', 'Apify API Token'),
      cufinder_api_key: translate('api.keys.cufinder', 'CUFinder API Key'),
      sendgrid_api_key: translate('api.keys.sendgrid', 'SendGrid API Key'),
      phantombuster_api_key: translate('api.keys.phantombuster', 'PhantomBuster API Key'),
      linkedin_li_at: translate('api.keys.linkedin', 'LinkedIn li_at Cookie'),
    }),
    [translate],
  );

  const normalizedCurrentRole = useMemo(
    () => normalizeRole(currentUser?.role),
    [currentUser],
  );

  const roleDisplayLabel = useMemo(
    () => (normalizedCurrentRole === 'admin'
      ? translate('user.role.admin', 'Admin')
      : translate('user.role.user', 'Standard user')),
    [normalizedCurrentRole, translate],
  );

  const roleBadgeClasses = useMemo(
    () => (normalizedCurrentRole === 'admin'
      ? 'bg-blue-500/20 text-blue-100 border border-blue-500/30'
      : 'bg-emerald-500/20 text-emerald-100 border border-emerald-400/30'),
    [normalizedCurrentRole],
  );

  const organizationSlug = useMemo(() => {
    if (!currentUser) return undefined;
    const directSlug = currentUser.organization_slug;
    if (typeof directSlug === 'string' && directSlug.trim().length > 0) {
      return directSlug.trim();
    }
    const orgSlug = currentUser.organization?.slug;
    if (typeof orgSlug === 'string' && orgSlug.trim().length > 0) {
      return orgSlug.trim();
    }
    return undefined;
  }, [currentUser]);

  const handleSelfPasswordReset = useCallback(async () => {
    if (!currentUser?.email) {
      error(translate('user.passwordReset.error.noEmail', 'We could not determine your email address. Contact your administrator.'));
      return;
    }
    setPasswordResetLoading(true);
    setPasswordResetFeedback(null);
    try {
      const response = await apiService.requestPasswordReset(currentUser.email, organizationSlug);
      const message = response.data?.message
        ?? translate('user.passwordReset.success', 'If your account is active, a reset link is on the way.');
      setPasswordResetFeedback({ kind: 'success', message });
      success(message);
    } catch (err) {
      console.error('Password reset request failed', err);
      let friendlyMessage = translate('user.passwordReset.error.generic', 'Unable to send reset instructions right now. Please try again later.');
      if (axios.isAxiosError(err)) {
        const apiMessage =
          (err.response?.data as { message?: string; detail?: string } | undefined)?.message
            ?? (err.response?.data as { detail?: string } | undefined)?.detail;
        if (typeof apiMessage === 'string' && apiMessage.trim().length > 0) {
          friendlyMessage = apiMessage;
        }
      }
      setPasswordResetFeedback({ kind: 'error', message: friendlyMessage });
      error(friendlyMessage);
    } finally {
      setPasswordResetLoading(false);
    }
  }, [currentUser, organizationSlug, translate, success, error]);

  const handleCancelProfileDelete = useCallback(() => {
    if (deleteLoading) {
      return;
    }
    setShowDeleteConfirm(false);
    setDeleteError(null);
  }, [deleteLoading]);

  const handleDeleteProfile = useCallback(async () => {
    if (deleteLoading) {
      return;
    }

    setDeleteLoading(true);
    setDeleteError(null);

    try {
      const response = await apiService.deleteCurrentProfile();
      if (response.status >= 200 && response.status < 300) {
        success(
          translate('user.delete.successTitle', 'Profile deleted'),
          translate('user.delete.successBody', 'Your Tallwave profile and cookies have been removed.'),
        );

        clearAccessToken();
        if (typeof window !== 'undefined') {
          try {
            window.sessionStorage.removeItem('preferredDashboardView');
            window.sessionStorage.removeItem('preferredSettingsTab');
          } catch (storageError) {
            console.warn('[Settings] Failed to clear session storage after profile deletion', storageError);
          }
        }

        setCurrentUser(null);
        router.push('/login');
        return;
      }

      const fallbackMessage =
        response.error ??
        response.message ??
        translate('user.delete.errorGeneric', 'Unable to delete your profile.');
      setDeleteError(fallbackMessage);
      error(
        translate('user.delete.errorTitle', 'Delete failed'),
        fallbackMessage,
      );
    } catch (err) {
      console.error('Failed to delete profile', err);
      const fallback = translate('user.delete.errorGeneric', 'Unable to delete your profile.');
      setDeleteError(fallback);
      error(
        translate('user.delete.errorTitle', 'Delete failed'),
        fallback,
      );
    } finally {
      setDeleteLoading(false);
      setShowDeleteConfirm(false);
    }
  }, [deleteLoading, error, router, success, translate]);

  const cookieStatusLabels = useMemo(
    () => ({
      pending: translate('cookie.status.pending', 'Pending validation'),
      valid: translate('cookie.status.valid', 'Valid'),
      invalid: translate('cookie.status.invalid', 'Invalid'),
      expired: translate('cookie.status.expired', 'Expired'),
      missing: translate('cookie.status.missing', 'Missing'),
    }),
    [translate],
  );

  const renderUserSettings = () => (
    <div className="space-y-6">
      <GlassCard className="p-4 border border-white/10 bg-white/5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-foreground">
              {translate('user.role.title', 'Access level')}
            </p>
            <p className="text-xs text-muted-foreground">
              {normalizedCurrentRole === 'admin'
                ? translate(
                    'user.role.adminCopy',
                    'You can manage seats, billing, and security controls in the admin workspace.',
                  )
                : translate(
                    'user.role.userCopy',
                    'Standard users can update personal preferences and request password resets here.',
                  )}
            </p>
          </div>
          <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${roleBadgeClasses}`}>
            <ShieldCheck className="h-4 w-4" />
            {roleDisplayLabel}
          </span>
        </div>
        {normalizedCurrentRole === 'admin' ? (
          <p className="mt-3 text-xs text-muted-foreground">
            {translate(
              'user.role.adminGuardrail',
              'Need to reset a teammate password? Use the Admin → Team Members tab so the action is audited.',
            )}
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            <p className="text-xs text-muted-foreground">
              {translate(
                'user.role.userGuardrail',
                'We will email a single-use reset link to the address on file. Links expire after 15 minutes.',
              )}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleSelfPasswordReset}
                disabled={passwordResetLoading}
                className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white/80 transition hover:bg-white/20 disabled:opacity-50"
              >
                {passwordResetLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
                {translate('user.role.resetCta', 'Email me a reset link')}
              </button>
              {passwordResetFeedback && (
                <span
                  className={`text-xs ${passwordResetFeedback.kind === 'success' ? 'text-emerald-300' : 'text-red-300'}`}
                >
                  {passwordResetFeedback.message}
                </span>
              )}
            </div>
          </div>
        )}
      </GlassCard>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('user.displayNameLabel', 'Display Name')}
          </label>
          <input
            type="text"
            value={userSettings.name}
            onChange={(e) => {
              setUserSettings({...userSettings, name: e.target.value});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('user.emailLabel', 'Email Address')}
          </label>
          <input
            type="email"
            value={userSettings.email}
            onChange={(e) => {
              setUserSettings({...userSettings, email: e.target.value});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('user.timezoneLabel', 'Timezone')}
          </label>
          <select
            value={userSettings.timezone}
            onChange={(e) => {
              setUserSettings({...userSettings, timezone: e.target.value});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="UTC">{translate('user.timezone.utc', 'UTC')}</option>
            <option value="America/New_York">{translate('user.timezone.eastern', 'Eastern Time')}</option>
            <option value="America/Chicago">{translate('user.timezone.central', 'Central Time')}</option>
            <option value="America/Denver">{translate('user.timezone.mountain', 'Mountain Time')}</option>
            <option value="America/Los_Angeles">{translate('user.timezone.pacific', 'Pacific Time')}</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('user.themeLabel', 'Theme')}
          </label>
          <select
            value={userSettings.theme}
            onChange={(e) => {
              setUserSettings({...userSettings, theme: e.target.value as 'light' | 'dark' | 'auto'});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="light">{translate('user.theme.light', 'Light')}</option>
            <option value="dark">{translate('user.theme.dark', 'Dark')}</option>
            <option value="auto">{translate('user.theme.auto', 'Auto')}</option>
          </select>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-foreground mb-4 flex items-center gap-2">
          <Bell className="w-5 h-5" />
          {translate('user.notifications.title', 'Notification Preferences')}
        </h3>
        <div className="space-y-3">
          {Object.entries(userSettings.notifications).map(([key, value]) => (
            <label key={key} className="flex items-center justify-between">
              <span className="text-foreground">
                {notificationLabels[key as keyof typeof notificationLabels] ??
                  translate(`user.notifications.${key}`, `${key.replace('_', ' ')} notifications`)}
              </span>
              <input
                type="checkbox"
                checked={value}
                onChange={(e) => {
                  setUserSettings({
                    ...userSettings,
                    notifications: {
                      ...userSettings.notifications,
                      [key]: e.target.checked
                    }
                  });
                  setHasChanges(true);
                }}
                className="w-4 h-4 text-blue-600 bg-background/10 border-white/20 rounded focus:ring-blue-500"
              />
            </label>
          ))}
      </div>
    </div>

      <GlassCard className="p-4 border border-red-500/40 bg-gradient-to-br from-red-900/30 via-black/20 to-amber-500/5">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Trash2 className="h-4 w-4 text-red-300" />
            <p className="text-sm font-semibold text-red-200">
              {translate('user.delete.title', 'Delete profile')}
            </p>
          </div>
          <p className="text-xs text-red-100/80">
            {translate(
              'user.delete.description',
              'Remove your Tallwave profile, cookie vault, and personalized preferences. This action cannot be undone.',
            )}
          </p>
          {deleteError && (
            <p className="text-xs text-red-200">
              {deleteError}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            {showDeleteConfirm ? (
              <>
                <button
                  type="button"
                  onClick={handleDeleteProfile}
                  disabled={deleteLoading}
                  className="inline-flex items-center gap-2 rounded-lg border border-red-600/60 bg-red-600/70 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white transition hover:bg-red-500/80 disabled:opacity-60"
                >
                  {deleteLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  {translate('user.delete.confirmCta', 'Confirm deletion')}
                </button>
                <button
                  type="button"
                  onClick={handleCancelProfileDelete}
                  disabled={deleteLoading}
                  className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-white/80 transition hover:bg-white/20 disabled:opacity-60"
                >
                  {translate('user.delete.cancelCta', 'Cancel')}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setDeleteError(null);
                  setShowDeleteConfirm(true);
                }}
                className="inline-flex items-center gap-2 rounded-lg border border-red-600/40 bg-red-600/30 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-red-100 transition hover:bg-red-600/40"
              >
                <Trash2 className="h-3.5 w-3.5" />
                {translate('user.delete.openCta', 'Delete my profile')}
              </button>
            )}
          </div>
        </div>
      </GlassCard>
    </div>
  );

  const renderSystemSettings = () => (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('system.autoApprovalLabel', 'Auto-approval Threshold')}
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={systemSettings.auto_approval_threshold}
            onChange={(e) => {
              setSystemSettings({...systemSettings, auto_approval_threshold: parseFloat(e.target.value)});
              setHasChanges(true);
            }}
            className="w-full"
          />
          <span className="text-sm text-muted-foreground">
            {(systemSettings.auto_approval_threshold * 100).toFixed(0)}% {translate('system.autoApprovalConfidence', 'confidence')}
          </span>
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('system.maxWorkflowsLabel', 'Max Concurrent Workflows')}
          </label>
          <input
            type="number"
            min="1"
            max="50"
            value={systemSettings.max_concurrent_workflows}
            onChange={(e) => {
              setSystemSettings({...systemSettings, max_concurrent_workflows: parseInt(e.target.value)});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('system.timeoutLabel', 'Workflow Timeout (minutes)')}
          </label>
          <input
            type="number"
            min="5"
            max="120"
            value={systemSettings.workflow_timeout_minutes}
            onChange={(e) => {
              setSystemSettings({...systemSettings, workflow_timeout_minutes: parseInt(e.target.value)});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('system.rateLimitLabel', 'Rate Limit (per minute)')}
          </label>
          <input
            type="number"
            min="10"
            max="1000"
            value={systemSettings.rate_limit_per_minute}
            onChange={(e) => {
              setSystemSettings({...systemSettings, rate_limit_per_minute: parseInt(e.target.value)});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-foreground">
          {translate('system.optionsTitle', 'System Options')}
        </h3>
        {[
          { key: 'debug_mode', icon: Monitor },
          { key: 'audit_logging', icon: Shield }
        ].map(({ key, icon: Icon }) => (
          <label key={key} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Icon className="w-4 h-4" />
              <span className="text-foreground">
                {systemOptionLabels[key as keyof typeof systemOptionLabels] ??
                  translate(`system.options.${key}`, key)}
              </span>
            </div>
            <input
              type="checkbox"
              checked={systemSettings[key as keyof SystemSettings] as boolean}
              onChange={(e) => {
                setSystemSettings({...systemSettings, [key]: e.target.checked});
                setHasChanges(true);
              }}
              className="w-4 h-4 text-blue-600 bg-background/10 border-white/20 rounded focus:ring-blue-500"
            />
          </label>
        ))}
      </div>
    </div>
  );

  const renderSecuritySettings = () => (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('security.sessionTimeoutLabel', 'Session Timeout (minutes)')}
          </label>
          <input
            type="number"
            min="30"
            max="1440"
            value={securitySettings.session_timeout_minutes}
            onChange={(e) => {
              setSecuritySettings({...securitySettings, session_timeout_minutes: parseInt(e.target.value)});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            {translate('security.maxFailedAttemptsLabel', 'Max Failed Login Attempts')}
          </label>
          <input
            type="number"
            min="3"
            max="10"
            value={securitySettings.max_failed_attempts}
            onChange={(e) => {
              setSecuritySettings({...securitySettings, max_failed_attempts: parseInt(e.target.value)});
              setHasChanges(true);
            }}
            className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-foreground">
          {translate('security.featuresTitle', 'Security Features')}
        </h3>
        {[
          {
            key: 'require_2fa' as const,
            label:
              securityToggleLabels.require_2fa ??
              translate('security.toggle.require_2fa', 'require_2fa'),
            value: securitySettings.require_2fa,
            toggle: (checked: boolean) =>
              setSecuritySettings({ ...securitySettings, require_2fa: checked }),
          },
          {
            key: 'ip_whitelist_enabled' as const,
            label:
              securityToggleLabels.ip_whitelist_enabled ??
              translate('security.toggle.ip_whitelist_enabled', 'ip_whitelist_enabled'),
            value: securitySettings.ip_whitelist_enabled,
            toggle: (checked: boolean) =>
              setSecuritySettings({ ...securitySettings, ip_whitelist_enabled: checked }),
          },
        ].map(({ key, label, value, toggle }) => (
          <label key={key} className="flex items-center justify-between">
            <span className="text-foreground">{label}</span>
            <input
              type="checkbox"
              checked={value}
              onChange={(e) => {
                toggle(e.target.checked);
                setHasChanges(true);
              }}
              className="w-4 h-4 text-blue-600 bg-background/10 border-white/20 rounded focus:ring-blue-500"
            />
          </label>
        ))}
      </div>
    </div>
  );

  const renderApiSettings = () => (
    <div className="space-y-6">
      <div className="mb-4 p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
        <div className="flex items-center gap-2 text-yellow-400 mb-2">
          <AlertTriangle className="w-4 h-4" />
          <span className="font-medium">{translate('api.notice.title', 'Security Notice')}</span>
        </div>
        <p className="text-sm text-yellow-200">
          {translate(
            'api.notice.description',
            'API keys are encrypted and stored securely. Never share your API keys or commit them to version control.',
          )}
        </p>
      </div>

      <div className="p-4 bg-primary/5 border border-primary/20 rounded-lg space-y-1">
        <p className="text-sm text-primary-foreground/80">
          {translate(
            'api.notice.mandatoryProviders',
            'Apify Saswave mutual discovery and SendGrid email delivery must be configured for every tenant.',
          )}
        </p>
        <p className="text-xs text-muted-foreground">
          {translate(
            'api.notice.optionalProviders',
            'PhantomBuster credentials remain optional and are only used for secondary enrichment after an approval ID is recorded.',
          )}
        </p>
      </div>

      <GlassCard className="p-4 border border-white/10 bg-background/30 backdrop-blur">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-foreground">
            {translate('api.providers.title', 'Provider status')}
          </h3>
          {providerHealthLoading && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
        </div>
        <div className="space-y-3">
          {(() => {
            if (providerHealthMap.size === 0) return [];
            const preferredOrder = ['apify', 'cufinder', 'cookieVault', 'cookieVerifier'];
            const dynamicKeys = Array.from(providerHealthMap.keys());
            const ordered = preferredOrder.filter((key) => dynamicKeys.includes(key));
            const remaining = dynamicKeys.filter((key) => !preferredOrder.includes(key));
            return [...ordered, ...remaining];
          })().map((key) => {
            const status = providerHealthMap.get(key);
            const configured = Boolean(status?.configured);
            const cookiesWarning = key === 'apify' && configured && status?.cookiesConfigured === false;
            const pendingCount =
              typeof status?.pendingRequests === 'number'
                ? status.pendingRequests
                : typeof status?.pendingRuns === 'number'
                  ? status.pendingRuns
                  : 0;
            const hasPendingQueue = pendingCount > 0;
            const lastEvent = status?.lastRequest ?? status?.lastRun ?? null;
            const lastQueuedAt = lastEvent?.requested_at ? new Date(lastEvent.requested_at) : null;
            const detailLines: React.ReactNode[] = [];

            if (hasPendingQueue) {
              detailLines.push(
                <p key="pending" className="mt-2 text-xs text-amber-200">
                  {translate(
                    'api.providers.pendingQueue',
                    `Pending requests queued until credentials are added: ${pendingCount}`,
                  )}
                </p>,
              );
            }

            if (lastQueuedAt) {
              detailLines.push(
                <p key="queuedAt" className="mt-1 text-xs text-muted-foreground">
                  {translate(
                    'api.providers.lastQueued',
                    `Last queued: ${lastQueuedAt.toLocaleString()}`,
                  )}
                </p>,
              );
            }

            if (cookiesWarning) {
              detailLines.push(
                <p key="cookiesWarning" className="mt-2 text-xs text-amber-300 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  {translate(
                    'api.providers.cookiesMissing',
                    'LinkedIn cookies are required for Apify runs. Upload li_at and JSESSIONID.',
                  )}
                </p>,
              );
            }

            if (!configured && (status?.disabledReason ?? status?.message)) {
              detailLines.push(
                <p key="disabledReason" className="mt-2 text-xs text-rose-200">
                  {status?.disabledReason ?? status?.message}
                </p>,
              );
            }

            if (key === 'cookieVault') {
              if (status?.keySource) {
                detailLines.push(
                  <p key="vault-source" className="mt-2 text-xs text-muted-foreground">
                    {translate(
                      'api.providers.cookieVaultSource',
                      `Key source: ${status.keySource}`,
                    )}
                  </p>,
                );
              }
              if (status?.kmsEnabled) {
                detailLines.push(
                  <p key="vault-kms" className="mt-1 text-xs text-emerald-200">
                    {translate('api.providers.cookieVaultKms', 'AWS KMS protection enabled')}
                  </p>,
                );
              }
            }

            if (key === 'cookieVerifier') {
              detailLines.push(
                <p key="verifier-mode" className="mt-2 text-xs text-muted-foreground">
                  {translate('api.providers.cookieVerifierMode', `Mode: ${status?.mode ?? 'unknown'}`)}
                </p>,
              );
              if (status?.reason && status?.message !== status.reason) {
                detailLines.push(
                  <p key="verifier-reason" className="mt-1 text-xs text-muted-foreground">
                    {status.reason}
                  </p>,
                );
              }
            }

            return (
              <div
                key={key}
                className="flex items-start justify-between rounded-lg border border-white/10 bg-background/10 p-3"
              >
                <div>
                  <p className="text-sm font-medium text-foreground capitalize">{key}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {status?.message ??
                      translate('api.providers.missing', 'Configuration pending for this integration.')}
                  </p>
                  {detailLines}
                </div>
                <div
                  className={`flex items-center gap-1 text-sm ${
                    configured ? 'text-emerald-400' : 'text-rose-400'
                  }`}
                >
                  {configured ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
                  <span>
                    {configured
                      ? translate('api.providers.ready', 'Ready')
                      : translate('api.providers.notReady', 'Action needed')}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </GlassCard>

      <div className="space-y-4">
        {[
          { key: 'openai_api_key', required: true },
          { key: 'apify_api_token', required: true },
          { key: 'cufinder_api_key', required: true },
          { key: 'sendgrid_api_key', required: false },
          { key: 'phantombuster_api_key', required: false },
          { key: 'linkedin_li_at', required: false }
        ].map(({ key, required }) => {
          const credentialKey = key as ApiCredentialKey;
          const value = apiCredentials.get(credentialKey) ?? '';
          const statusInfo = apiCredentialStatus.get(credentialKey);
          const configured = statusInfo?.configured ?? false;
          const maskedSecret = statusInfo?.masked ?? null;
          const isVisible = showApiKeys.get(credentialKey) ?? false;
          const label = apiFieldLabels[key as keyof typeof apiFieldLabels] ?? translate(`api.keys.${key}`, key);
          const placeholder = translate(
            `api.keysPlaceholders.${key}`,
            `Enter your ${label.toLowerCase()}`,
          );

          return (
            <div key={key}>
              <label className="block text-sm font-medium text-foreground mb-2">
                {label}
                {required && <span className="text-red-400 ml-1">*</span>}
              </label>
              <div className="relative">
                <input
                  type={isVisible ? 'text' : 'password'}
                  value={value}
                  onChange={(e) => {
                    setApiCredentials((prev) => {
                      const next = new Map(prev);
                      next.set(credentialKey, e.target.value);
                      return next;
                    });
                    setHasChanges(true);
                  }}
                  placeholder={`${placeholder} (${translate('api.keys.leaveBlank', 'leave blank to keep current')})`}
                  className="w-full px-3 py-2 pr-10 bg-background/10 border border-white/20 rounded-lg text-foreground placeholder-white/50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button
                  type="button"
                  onClick={() => toggleApiKeyVisibility(credentialKey)}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-white/50 hover:text-white"
                >
                  {isVisible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {configured && !value && (
                <p className="text-xs text-muted-foreground mt-1">
                  {translate('api.keys.configured', 'Stored securely')}
                  {maskedSecret ? ` · ${maskedSecret}` : ''}
                </p>
              )}
              {!configured && !value && (
                <p className="text-xs text-muted-foreground mt-1">
                  {translate('api.keys.notConfigured', 'Not configured')}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );

  const renderCookieJarSettings = () => {
    const status = cookieStatus?.status ?? 'missing';
    const badgeClass = getCookieStatusClasses(status);

    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <CookieIcon className="w-5 h-5 text-blue-400" />
          <div>
            <h3 className="text-lg font-semibold text-foreground">{translate('cookie.title', 'LinkedIn Cookie Jar')}</h3>
            <p className="text-sm text-muted-foreground">
              {translate(
                'cookie.description',
                'Upload encrypted LinkedIn cookies to enable personalized outreach and background validation checks.',
              )}
            </p>
            <p className="text-xs text-amber-300 mt-1">
              {translate(
                'cookie.safetyNotice',
                'Only submit LinkedIn session cookies. Never paste HR, finance, or PHI data—everything here is encrypted in the vault and audited.',
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              {translate(
                'cookie.retention',
                'Vault entries are versioned, tenant-isolated, and rotated automatically when teammates leave the organization.',
              )}
            </p>
            {currentUser?.email && (
              <p className="text-xs text-muted-foreground mt-1">
                {translate('cookie.signedInAs', 'Signed in as')} {currentUser.email}
              </p>
            )}
          </div>
        </div>

        {canManageSettings ? (
        <form onSubmit={handleCookieJarSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-2">
              {translate('cookie.liAtLabel', 'li_at Cookie')}
            </label>
            <textarea
              value={cookieForm.li_at}
              onChange={(event) => handleCookieInputChange('li_at', event.target.value)}
              className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground placeholder-white/40 focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={2}
              placeholder={translate('cookie.liAtPlaceholder', 'Paste the li_at cookie value')}
              required
            />
            <p className="text-xs text-muted-foreground mt-1">
              {translate(
                'cookie.liAtHelp',
                'Copy this value from your browser developer tools while logged into LinkedIn. Treat it like a password.',
              )}
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">
                {translate('cookie.jsessionIdLabel', 'JSESSIONID (optional)')}
              </label>
              <input
                type="text"
                value={cookieForm.jsessionid ?? ''}
                onChange={(event) => handleCookieInputChange('jsessionid', event.target.value)}
                className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground placeholder-white/40 focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder={translate('cookie.jsessionIdPlaceholder', 'Paste JSESSIONID')}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">
                {translate('cookie.userAgentLabel', 'User Agent (optional)')}
              </label>
              <input
                type="text"
                value={cookieForm.user_agent ?? ''}
                onChange={(event) => handleCookieInputChange('user_agent', event.target.value)}
                className="w-full px-3 py-2 bg-background/10 border border-white/20 rounded-lg text-foreground placeholder-white/40 focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder={translate('cookie.userAgentPlaceholder', 'Mozilla/5.0 (Macintosh; Intel Mac OS X ...)')}
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={cookieLoading}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-blue-500/20 border border-blue-500/30 text-blue-100 hover:bg-blue-500/30 transition-colors disabled:opacity-50"
            >
              {cookieLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {cookieLoading
                ? translate('cookie.buttons.saving', 'Saving…')
                : translate('cookie.buttons.upload', 'Upload Cookies')}
            </button>
            <button
              type="button"
              onClick={handleCookieRevalidate}
              disabled={cookieLoading || !cookieStatus?.id}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg border border-white/20 text-white/80 hover:bg-white/10 transition-colors disabled:opacity-50"
            >
              <RefreshCw className="w-4 h-4" />
              {translate('cookie.buttons.revalidate', 'Re-validate')}
            </button>
          </div>
        </form>
        ) : (
        <GlassCard className="p-4 border border-white/10 bg-white/5">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-5 h-5 text-blue-400" />
            <div>
              <p className="text-sm font-semibold text-foreground">
                {translate('cookie.readOnlyTitle', 'LinkedIn cookie management is restricted')}
              </p>
              <p className="text-xs text-muted-foreground">
                {translate(
                  'cookie.readOnlyMessage',
                  'Only organization administrators can upload or revalidate LinkedIn cookies. Contact your admin for assistance.',
                )}
              </p>
            </div>
          </div>
        </GlassCard>
        )}

        <GlassCard className="p-4 border border-white/10 bg-white/5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-foreground">
                {translate('cookie.currentStatus', 'Current Status')}
              </p>
              <p className="text-xs text-muted-foreground">
                {translate('cookie.lastValidated', 'Last validated')}:{' '}
                {formatTimestamp(cookieStatus?.last_validated_at)}
              </p>
            </div>
            <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${badgeClass}`}>
              {cookieStatusLabels[status as keyof typeof cookieStatusLabels] ?? status}
            </span>
          </div>
          {status === 'missing' && (
            <div className="mt-3 inline-flex items-center gap-2 text-xs text-amber-300">
              <AlertCircle className="w-4 h-4" />
              {translate(
                'cookie.missingHint',
                'No cookies uploaded yet. Upload your LinkedIn session to activate outreach features.',
              )}
            </div>
          )}
        </GlassCard>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <SettingsIcon className="w-6 h-6 text-blue-400" />
          <h2 className="text-xl font-semibold text-foreground">Settings</h2>
        </div>

        {hasChanges && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleResetToDefaults}
              className="px-3 py-1.5 text-sm bg-gray-500/20 hover:bg-gray-500/30 border border-gray-500/30 rounded-lg text-white/80 transition-colors flex items-center gap-2"
            >
              <RotateCcw className="w-4 h-4" />
              Reset
            </button>
            <button
              onClick={handleSaveSettings}
              disabled={loading}
              className="px-4 py-1.5 text-sm bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/30 rounded-lg text-blue-200 transition-colors flex items-center gap-2"
            >
              <Save className="w-4 h-4" />
              Save Changes
            </button>
          </div>
        )}
      </div>

      <GlassCard className="p-6">
        <div className="flex flex-col lg:flex-row gap-6">
          <div className="lg:w-1/4">
            <nav className="space-y-2">
              {tabs.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveTab(id)}
                  className={`w-full text-left px-4 py-3 rounded-lg transition-colors flex items-center gap-3 ${
                    activeTab === id
                      ? 'bg-blue-500/20 border border-blue-500/30 text-blue-200'
                      : 'hover:bg-white/5 text-white/80'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span className="font-medium">{label}</span>
                </button>
              ))}
            </nav>
          </div>

          <div className="lg:w-3/4">
            <div className="min-h-[500px]">
              {activeTab === 'user' && renderUserSettings()}
              {activeTab === 'system' && canManageSettings && renderSystemSettings()}
              {activeTab === 'security' && canManageSettings && renderSecuritySettings()}
              {activeTab === 'api' && canManageSettings && renderApiSettings()}
              {activeTab === 'cookie-jar' && renderCookieJarSettings()}
            </div>
          </div>
        </div>
      </GlassCard>
    </div>
  );
}
