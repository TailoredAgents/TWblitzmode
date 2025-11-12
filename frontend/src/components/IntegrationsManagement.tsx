import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Settings, CheckCircle2, AlertTriangle, RefreshCw, Eye, EyeOff, Copy, ExternalLink } from 'lucide-react';
import GlassCard from './ui/GlassCard';
import { useToastActions } from './ui/ToastContainer';
import { cn } from '../lib/utils';
import {
  apiService,
  type CredentialSecretStatus,
  type CredentialSettingsPayload,
  type CredentialSecretUpdate,
  type UpdateCredentialSettingsPayload,
} from '../services/api';

interface Integration {
  id: string;
  name: string;
  description: string;
  category: 'ai' | 'crm' | 'email' | 'data' | 'automation';
  status: 'connected' | 'disconnected' | 'error' | 'testing';
  config: Map<string, string>;
  secretMetadata: Map<string, CredentialSecretStatus | undefined>;
  last_sync?: string;
  icon: string;
  docs_url: string;
  required_fields: string[];
  optional_fields: string[];
}


const integrationCatalog: Array<{
  id: string;
  name: string;
  description: string;
  category: Integration['category'];
  icon: string;
  docs_url: string;
  required_fields: string[];
  optional_fields: string[];
}> = [
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'AI-powered content generation and analysis',
    category: 'ai',
    icon: '🤖',
    docs_url: 'https://platform.openai.com/docs',
    required_fields: ['openai_api_key'],
    optional_fields: ['openai_org']
  },
  {
    id: 'apify',
    name: 'Apify',
    description: 'Mandatory Saswave mutual discovery provider for every tenant',
    category: 'data',
    icon: '🕸️',
    docs_url: 'https://docs.apify.com',
    required_fields: ['apify_token'],
    optional_fields: ['apify_webhook_secret', 'apify_li_cookie_secret_name']
  },
  {
    id: 'cufinder',
    name: 'CUFinder',
    description: 'Email discovery and verification service',
    category: 'email',
    icon: '📧',
    docs_url: 'https://cufinder.io/docs',
    required_fields: ['cufinder_api_key'],
    optional_fields: []
  },
  {
    id: 'sendgrid',
    name: 'SendGrid',
    description: 'Exclusive provider for all introduction and notification emails',
    category: 'email',
    icon: '📮',
    docs_url: 'https://docs.sendgrid.com',
    required_fields: ['sendgrid_api_key', 'sendgrid_from_email'],
    optional_fields: ['sendgrid_from_name']
  },
  {
    id: 'phantombuster',
    name: 'PhantomBuster',
    description: 'Optional secondary enrichment that runs only after approvals',
    category: 'automation',
    icon: '👻',
    docs_url: 'https://phantombuster.com/api-documentation',
    required_fields: ['phantombuster_api_key'],
    optional_fields: []
  },
  {
    id: 'linkedin',
    name: 'LinkedIn',
    description: 'Professional networking and lead generation',
    category: 'data',
    icon: '🔗',
    docs_url: 'https://www.linkedin.com',
    required_fields: ['linkedin_li_at', 'linkedin_jsessionid'],
    optional_fields: ['linkedin_cookies_json']
  },
  {
    id: 'grok',
    name: 'Grok',
    description: 'Development assistance and debugging guidance',
    category: 'ai',
    icon: '🧠',
    docs_url: 'https://docs.x.ai',
    required_fields: ['grok_api_key'],
    optional_fields: []
  }
];

const secretFieldAliasEntries: Array<[string, string]> = [['apify_token', 'apify_api_token']];
const secretFieldAliasMap = new Map<string, string>(secretFieldAliasEntries);

const resolveSecretKey = (field: string): string => secretFieldAliasMap.get(field) ?? field;

const isSecretField = (field: string): boolean => {
  const normalized = field.toLowerCase();
  if (secretFieldAliasMap.has(field)) {
    return true;
  }
  return (
    normalized.includes('key') ||
    normalized.includes('token') ||
    normalized.includes('secret') ||
    normalized.includes('li_at') ||
    normalized.includes('jsessionid') ||
    normalized.includes('cookie')
  );
};

interface IntegrationsManagementProps {
  organizationId: number;
}

const IntegrationsManagement: React.FC<IntegrationsManagementProps> = ({ organizationId }) => {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingIntegration, setTestingIntegration] = useState<string | null>(null);
  const [editingIntegration, setEditingIntegration] = useState<Integration | null>(null);
  const [savingIntegration, setSavingIntegration] = useState(false);
  const [showApiKey, setShowApiKey] = useState<Map<string, boolean>>(() => new Map());
  const [loadError, setLoadError] = useState<string | null>(null);
  const { success, error } = useToastActions();
  const formRef = useRef<HTMLFormElement | null>(null);

  useEffect(() => {
    if (editingIntegration) {
      setSavingIntegration(false);
    }
  }, [editingIntegration]);

  const normalizeIntegrations = useCallback((settings: CredentialSettingsPayload): Integration[] => {
    const secretsMap = new Map<string, CredentialSecretStatus>();
    Object.entries(settings.secrets ?? {}).forEach(([key, value]) => {
      secretsMap.set(key, value as CredentialSecretStatus);
    });
    const additionalEntries = Object.entries(settings).filter(([key]) => key !== 'secrets' && key !== 'integrations');
    const additionalMap = new Map<string, unknown>(additionalEntries);

    return integrationCatalog.map((definition) => {
      const fieldKeys = [...definition.required_fields, ...definition.optional_fields];
      const configEntries = fieldKeys.map<[string, string]>((field) => {
        const storageKey = resolveSecretKey(field);
        const secretEntry = secretsMap.get(storageKey);
        const secretValue = secretEntry && typeof secretEntry.masked === 'string' ? secretEntry.masked : '';
        const additionalValue = additionalMap.has(field) ? additionalMap.get(field) : additionalMap.get(storageKey);
        const normalizedValue =
          secretValue && secretValue.length > 0
            ? secretValue
            : typeof additionalValue === 'string'
              ? additionalValue
              : additionalValue != null
                ? String(additionalValue)
                : '';
        return [field, normalizedValue];
      });
      const config = new Map<string, string>(configEntries);
      const secretMetadata = new Map<string, CredentialSecretStatus | undefined>();
      fieldKeys.forEach((field) => {
        const storageKey = resolveSecretKey(field);
        secretMetadata.set(field, secretsMap.get(storageKey));
      });

      const missing = definition.required_fields.filter((field) => {
        const storageKey = resolveSecretKey(field);
        const secretEntry = secretsMap.get(storageKey);
        if (secretEntry) {
          return !secretEntry.configured;
        }
        const fallback = config.get(field);
        return !fallback || fallback.trim().length === 0;
      });

      let status: Integration['status'] = missing.length === 0 ? 'connected' : 'disconnected';

      if (definition.id === 'sendgrid' && status === 'connected') {
        const fromEmail = config.get('sendgrid_from_email') ?? '';
        if (fromEmail.trim().length === 0) {
          status = 'disconnected';
        }
      }

      if (definition.id === 'linkedin' && status === 'connected') {
        const liAtConfigured = secretsMap.get(resolveSecretKey('linkedin_li_at'))?.configured ?? false;
        const jsessionConfigured =
          secretsMap.get(resolveSecretKey('linkedin_jsessionid'))?.configured ??
          Boolean(config.get('linkedin_jsessionid')?.trim());
        if (!liAtConfigured || !jsessionConfigured) {
          status = 'disconnected';
        }
      }

      const lastSyncRaw = additionalMap.get(`${definition.id}_last_sync`);
      const lastSyncValue =
        typeof lastSyncRaw === 'string'
          ? lastSyncRaw
          : lastSyncRaw != null
            ? String(lastSyncRaw)
            : undefined;

      return {
        ...definition,
        status,
        config,
        secretMetadata,
        ...(lastSyncValue ? { last_sync: lastSyncValue } : {}),
      };
    });
  }, []);

  const loadIntegrations = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await apiService.getTenantIntegrations(organizationId);
      const settings = (response.data ?? { secrets: {}, integrations: {} }) as CredentialSettingsPayload;
      setIntegrations(normalizeIntegrations(settings));
    } catch (_err) {
      console.error('Failed to load integrations:', _err);
      setIntegrations([]);
      setLoadError('Failed to load integration settings. Verify admin access and API availability.');
    } finally {
      setLoading(false);
    }
  }, [organizationId, normalizeIntegrations]);

  useEffect(() => {
    void loadIntegrations();
  }, [loadIntegrations]);

  const handleTestIntegration = async (integration: Integration) => {
    setTestingIntegration(integration.id);
    setIntegrations((prev) =>
      prev.map((item) => (item.id === integration.id ? { ...item, status: 'testing' } : item))
    );

    const resolveErrorMessage = (err: unknown): string => {
      if (typeof err === 'string') {
        return err;
      }
      if (err && typeof err === 'object') {
        const anyErr = err as { message?: string; response?: { data?: unknown } };
        const responseData = anyErr.response?.data;
        if (responseData) {
          if (typeof responseData === 'object' && responseData !== null) {
            const responseRecord = responseData as Record<string, unknown>;
            const detailCandidate = responseRecord['detail'];
            if (typeof detailCandidate === 'string' && detailCandidate.trim().length > 0) {
              return detailCandidate;
            }
            const messageCandidate = responseRecord['message'];
            if (typeof messageCandidate === 'string' && messageCandidate.trim().length > 0) {
              return messageCandidate;
            }
            const errorCandidate = responseRecord['error'];
            if (typeof errorCandidate === 'string' && errorCandidate.trim().length > 0) {
              return errorCandidate;
            }
          }
        }
        if (typeof anyErr.message === 'string' && anyErr.message.trim().length > 0) {
          return anyErr.message;
        }
      }
      return 'Unable to validate integration credentials. Please try again.';
    };

    try {
      const response = await apiService.testIntegrationConnection(integration.id);
      const result = response.data;

      if (!result) {
        throw new Error('Validation service returned an empty response.');
      }

      const normalizedStatus = result.status?.toLowerCase?.() ?? '';
      const isHealthy = normalizedStatus === 'connected' || normalizedStatus === 'healthy';
      const nextStatus: Integration['status'] = isHealthy ? 'connected' : 'error';

      const health = (result.health ?? {}) as Record<string, unknown>;
      const lastSuccess = typeof health['last_success'] === 'string' ? (health['last_success'] as string) : undefined;
      const lastCheck = typeof health['last_check'] === 'string' ? (health['last_check'] as string) : undefined;
      const timestamp = lastSuccess ?? lastCheck ?? new Date().toISOString();

      setIntegrations((prev) =>
        prev.map((item) =>
          item.id === integration.id ? { ...item, status: nextStatus, last_sync: timestamp } : item
        )
      );

      if (isHealthy) {
        const successMessage = result.message ?? 'Integration credentials validated successfully.';
        success(`${integration.name} credentials validated`, successMessage);
      } else {
        const failureMessage = result.message ?? 'Validation failed. Review configuration and try again.';
        error(`${integration.name} validation failed`, failureMessage);
      }

      await loadIntegrations();
    } catch (err) {
      const message = resolveErrorMessage(err);
      setIntegrations((prev) =>
        prev.map((item) => (item.id === integration.id ? { ...item, status: 'error' } : item))
      );
      error(`${integration.name} validation failed`, message);
    } finally {
      setTestingIntegration(null);
    }
  };

  const handleSaveIntegration = async (integration: Integration, newConfig: Map<string, string>) => {
    const secretUpdates = new Map<string, CredentialSecretUpdate>();
    const additionalUpdates = new Map<string, string | null>();

    newConfig.forEach((value, key) => {
      const rawValue = value ?? '';
      const trimmed = rawValue.trim();

      if (isSecretField(key)) {
        const storageKey = resolveSecretKey(key);
        const secretDetails = integration.secretMetadata.get(key);
        const maskedPlaceholder =
          typeof secretDetails?.masked === 'string' ? secretDetails.masked : null;
        const matchesStoredMask =
          Boolean(secretDetails?.configured) && maskedPlaceholder
            ? rawValue === maskedPlaceholder || trimmed === maskedPlaceholder
            : false;

        if (trimmed.length === 0 || matchesStoredMask) {
          return;
        }

        secretUpdates.set(storageKey, { value: rawValue });
        return;
      }

      additionalUpdates.set(key, trimmed.length > 0 ? rawValue : null);
    });

    const extraPayload = Object.fromEntries(additionalUpdates) as Record<string, string | null>;
    const requestPayload: UpdateCredentialSettingsPayload = { ...extraPayload };
    if (secretUpdates.size > 0) {
      requestPayload.secrets = Object.fromEntries(secretUpdates) as Record<string, CredentialSecretUpdate>;
    }

    const resolveSaveError = (err: unknown): string => {
      if (typeof err === 'string') {
        return err;
      }
      if (err && typeof err === 'object') {
        const anyErr = err as { message?: string; response?: { data?: unknown } };
        const responseData = anyErr.response?.data;
        if (typeof responseData === 'string' && responseData.trim().length > 0) {
          return responseData;
        }
        if (responseData && typeof responseData === 'object') {
          const responseRecord = responseData as Record<string, unknown>;
          const detail = responseRecord.detail;
          const message = responseRecord.message;
          if (typeof detail === 'string' && detail.trim().length > 0) {
            return detail;
          }
          if (typeof message === 'string' && message.trim().length > 0) {
            return message;
          }
        }
        if (typeof anyErr.message === 'string' && anyErr.message.trim().length > 0) {
          return anyErr.message;
        }
      }
      return 'Unable to save integration configuration. Please try again.';
    };

    setSavingIntegration(true);
    try {
      const response = await apiService.setTenantIntegrations(organizationId, requestPayload);
      const updatedSettings = (response.data ?? { secrets: {}, integrations: {} }) as CredentialSettingsPayload;
      setIntegrations(normalizeIntegrations(updatedSettings));

      const payloadMessage = response.message ?? (response.data as unknown as { message?: string })?.message;
      success(payloadMessage ?? `${integration.name} configuration saved`);
      setEditingIntegration(null);
      void loadIntegrations();
    } catch (err) {
      const message = resolveSaveError(err);
      error('Failed to save configuration', message);
    } finally {
      setSavingIntegration(false);
    }
  };

  const handleToggleApiKeyVisibility = (integrationId: string) => {
    setShowApiKey((prev) => {
      const next = new Map(prev);
      const current = next.get(integrationId) ?? false;
      next.set(integrationId, !current);
      return next;
    });
  };

  const handleCopyApiKey = async (apiKey: string) => {
    if (!apiKey) {
      return;
    }

    const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined;
    if (!clipboard || typeof clipboard.writeText !== 'function') {
      error('Clipboard unavailable', 'Your browser blocked clipboard access. Copy manually instead.');
      return;
    }

    try {
      await clipboard.writeText(apiKey);
      success('API key copied to clipboard');
    } catch (err) {
      console.error('Failed to copy API key:', err);
      error('Failed to copy API key', 'Copy this value manually instead.');
    }
  };

  const handleCopySecretField = async (integration: Integration, field: string) => {
    const storageKey = resolveSecretKey(field);
    const secretDetails = integration.secretMetadata.get(field);
    const maskedValue =
      typeof secretDetails?.masked === 'string' ? secretDetails.masked : null;
    const formElement = formRef.current;
    const formControl = formElement?.elements.namedItem(field);
    const liveValueRaw = (() => {
      if (formControl instanceof HTMLInputElement || formControl instanceof HTMLTextAreaElement || formControl instanceof HTMLSelectElement) {
        return String(formControl.value ?? '');
      }
      return '';
    })();
    const liveValueTrimmed = liveValueRaw.trim();
    const matchesStoredMask =
      Boolean(secretDetails?.configured) && maskedValue
        ? liveValueRaw === maskedValue || liveValueTrimmed === maskedValue
        : false;

    if (liveValueTrimmed && (!secretDetails?.configured || !matchesStoredMask)) {
      await handleCopyApiKey(liveValueRaw);
      return;
    }

    if (!secretDetails?.configured || !secretDetails.vaultItemId) {
      error('No stored credential', 'Paste a new value to copy it.');
      return;
    }

    try {
      const response = await apiService.getCredentialSecretValue(storageKey, organizationId);
      const payload = response.data as { value?: string; secret?: string } | null | undefined;
      const secretValue = payload?.value ?? payload?.secret ?? null;

      if (!secretValue) {
        throw new Error('Secret response missing value');
      }

      await handleCopyApiKey(secretValue);
    } catch (err) {
      console.error(`Failed to fetch credential ${storageKey} for copy:`, err);
      error('Failed to fetch credential', 'Re-enter or rotate the credential to copy it.');
    }
  };

  const getStatusIcon = (status: Integration['status']) => {
    switch (status) {
      case 'connected': return <CheckCircle2 className="w-5 h-5 text-green-500" />;
      case 'disconnected': return <AlertTriangle className="w-5 h-5 text-gray-400" />;
      case 'error': return <AlertTriangle className="w-5 h-5 text-red-500" />;
      case 'testing': return <RefreshCw className="w-5 h-5 text-blue-500 animate-spin" />;
    }
  };

  const getStatusColor = (status: Integration['status']) => {
    switch (status) {
      case 'connected': return 'text-green-600 bg-green-100';
      case 'disconnected': return 'text-gray-600 bg-gray-100';
      case 'error': return 'text-red-600 bg-red-100';
      case 'testing': return 'text-blue-600 bg-blue-100';
    }
  };

  const getCategoryColor = (category: Integration['category']) => {
    switch (category) {
      case 'ai': return 'text-blue-600 bg-blue-100';
      case 'crm': return 'text-blue-600 bg-blue-100';
      case 'email': return 'text-green-600 bg-green-100';
      case 'data': return 'text-orange-600 bg-orange-100';
      case 'automation': return 'text-indigo-600 bg-indigo-100';
    }
  };

  const maskApiKey = (key: string) => {
    if (!key) return 'Not configured';
    if (key.includes('•')) {
      return key;
    }
    return key.substring(0, 8) + '...' + key.substring(key.length - 4);
  };

  const statusCounts = integrations.reduce(
    (acc, integrationItem) => {
      if (integrationItem.status === 'connected') {
        acc.connected += 1;
      } else if (integrationItem.status === 'disconnected') {
        acc.disconnected += 1;
      } else if (integrationItem.status === 'error') {
        acc.error += 1;
      }
      return acc;
    },
    { connected: 0, disconnected: 0, error: 0 }
  );
  const totalIntegrations = integrations.length;
  const healthScore =
    totalIntegrations === 0 ? 0 : Math.round((statusCounts.connected / totalIntegrations) * 100);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Integrations</h2>
          <p className="text-muted-foreground">Configure API keys and service integrations</p>
        </div>
        <button
          onClick={loadIntegrations}
          className="inline-flex items-center gap-2 px-4 py-2 bg-muted hover:bg-muted/80 text-muted-foreground hover:text-foreground rounded-lg transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {loadError && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {loadError}
        </div>
      )}

      {/* Integration Cards */}
      {loading ? (
        <GlassCard className="p-8">
          <div className="flex items-center justify-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        </GlassCard>
      ) : (
        <div className="grid gap-4">
          {integrations.map(integration => {
            const revealSecret = showApiKey.get(integration.id) ?? false;

            return (
            <GlassCard key={integration.id} className="p-6">
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4 flex-1">
                  <div className="text-2xl">{integration.icon}</div>
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-lg font-semibold">{integration.name}</h3>
                      <span className={cn('px-2 py-1 rounded-full text-xs font-medium', getStatusColor(integration.status))}>
                        {integration.status}
                      </span>
                      <span className={cn('px-2 py-1 rounded-full text-xs font-medium', getCategoryColor(integration.category))}>
                        {integration.category}
                      </span>
                    </div>
                    <p className="text-muted-foreground text-sm mb-3">{integration.description}</p>

                    {/* Configuration Preview */}
                    <div className="space-y-2 mb-4">
                      {integration.required_fields.map((field) => {
                        const secretField = isSecretField(field);
                        const fieldValue = integration.config.get(field) ?? '';
                        const displayedValue = secretField
                          ? revealSecret
                            ? fieldValue || 'Not set'
                            : maskApiKey(fieldValue)
                          : fieldValue || 'Not set';

                        return (
                          <div key={field} className="flex items-center justify-between text-sm">
                            <span className="text-muted-foreground capitalize">
                              {field.replace('_', ' ')}:
                            </span>
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-xs">{displayedValue}</span>
                              {secretField ? (
                                <button
                                  onClick={() => handleToggleApiKeyVisibility(integration.id)}
                                  className="p-1 hover:bg-muted/50 rounded"
                                >
                                  {revealSecret ? (
                                    <EyeOff className="w-3 h-3" />
                                  ) : (
                                    <Eye className="w-3 h-3" />
                                  )}
                                </button>
                              ) : null}
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {integration.last_sync && (
                      <p className="text-xs text-muted-foreground">
                        Last synced: {new Date(integration.last_sync).toLocaleString()}
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <a
                    href={integration.docs_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-2 hover:bg-muted/50 rounded-lg transition-colors"
                    title="Documentation"
                  >
                    <ExternalLink className="w-4 h-4" />
                  </a>

                  <button
                    onClick={() => setEditingIntegration(integration)}
                    className="p-2 hover:bg-muted/50 rounded-lg transition-colors"
                    title="Configure"
                  >
                    <Settings className="w-4 h-4" />
                  </button>

                  <button
                    onClick={() => handleTestIntegration(integration)}
                    disabled={testingIntegration === integration.id}
                    className="inline-flex items-center gap-2 px-3 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                  >
                    {testingIntegration === integration.id ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        Testing
                      </>
                    ) : (
                      <>
                        {getStatusIcon(integration.status)}
                        {integration.status === 'connected' ? 'Retest' : 'Test'}
                      </>
                    )}
                  </button>
                </div>
              </div>
            </GlassCard>
            );
          })}
        </div>
      )}

      {/* Configuration Modal */}
      {editingIntegration && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <GlassCard className="w-full max-w-2xl p-6">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <span className="text-2xl">{editingIntegration.icon}</span>
                <h3 className="text-xl font-semibold">Configure {editingIntegration.name}</h3>
              </div>
              <button
                onClick={() => setEditingIntegration(null)}
                className="p-2 hover:bg-muted/50 rounded-lg transition-colors"
              >
                ✕
              </button>
            </div>

            <form
              ref={formRef}
              onSubmit={async (e) => {
                e.preventDefault();
                const formData = new FormData(e.currentTarget);
                const configEntries = Array.from(formData.entries()).map<[string, string]>(([key, value]) => [
                  key,
                  typeof value === 'string' ? value : value.toString(),
                ]);
                await handleSaveIntegration(editingIntegration, new Map(configEntries));
              }}
            >
              <div className="space-y-4">
                {/* Required Fields */}
                <div>
                  <h4 className="font-medium mb-3">Required Configuration</h4>
                  {editingIntegration.required_fields.map(field => {
                    const secretField = isSecretField(field);
                    const inputId = `${field}-input`;
                    const labelText = field.replace(/_/g, ' ');
                    return (
                      <div key={field} className="mb-4">
                        <label className="block text-sm font-medium mb-2 capitalize" htmlFor={inputId}>
                          {labelText}
                        </label>
                        <div className="relative">
                          <input
                            type={secretField ? 'password' : 'text'}
                            name={field}
                            id={inputId}
                            aria-label={labelText}
                            defaultValue={editingIntegration.config.get(field) ?? ''}
                            className="w-full px-3 py-2 bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20"
                            required
                          />
                          {secretField ? (
                            <button
                              type="button"
                              onClick={() => {
                                void handleCopySecretField(editingIntegration, field);
                              }}
                              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-muted/50 rounded"
                              title="Copy to clipboard"
                            >
                              <Copy className="w-4 h-4" />
                            </button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Optional Fields */}
                {editingIntegration.optional_fields.length > 0 && (
                  <div>
                    <h4 className="font-medium mb-3">Optional Configuration</h4>
                    {editingIntegration.optional_fields.map(field => {
                      const secretField = isSecretField(field);
                      const inputId = `${field}-input`;
                      const labelText = field.replace(/_/g, ' ');
                      return (
                        <div key={field} className="mb-4">
                          <label className="block text-sm font-medium mb-2 capitalize" htmlFor={inputId}>
                            {labelText}
                          </label>
                          <div className="relative">
                            <input
                              type={secretField ? 'password' : 'text'}
                              name={field}
                              id={inputId}
                              aria-label={labelText}
                              defaultValue={editingIntegration.config.get(field) ?? ''}
                              className="w-full px-3 py-2 bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20"
                            />
                            {secretField ? (
                              <button
                                type="button"
                                onClick={() => {
                                  void handleCopySecretField(editingIntegration, field);
                                }}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-muted/50 rounded"
                                title="Copy to clipboard"
                              >
                                <Copy className="w-4 h-4" />
                              </button>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-end gap-3 mt-6 pt-6 border-t">
                <button
                  type="button"
                  onClick={() => {
                    setSavingIntegration(false);
                    setEditingIntegration(null);
                  }}
                  className="px-4 py-2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingIntegration}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {savingIntegration ? (
                    <span className="inline-flex items-center gap-2">
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      Saving...
                    </span>
                  ) : (
                    'Save Configuration'
                  )}
                </button>
              </div>
            </form>
          </GlassCard>
        </div>
      )}

      {/* Integration Status Summary */}
      <GlassCard className="p-6">
        <h3 className="text-lg font-semibold mb-4">Integration Status</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
          <div>
            <div className="text-2xl font-bold text-green-600">
              {statusCounts.connected}
            </div>
            <div className="text-sm text-muted-foreground">Connected</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-gray-500">
              {statusCounts.disconnected}
            </div>
            <div className="text-sm text-muted-foreground">Not Connected</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-red-500">
              {statusCounts.error}
            </div>
            <div className="text-sm text-muted-foreground">Errors</div>
          </div>
          <div>
            <div className="text-2xl font-bold text-primary">
              {healthScore}%
            </div>
            <div className="text-sm text-muted-foreground">Health Score</div>
          </div>
        </div>
      </GlassCard>
    </div>
  );
};

export default IntegrationsManagement;
