/* eslint-disable max-lines */
// API service for Tallwave dashboard

import axios, {
  AxiosHeaders,
  type AxiosError,
  type AxiosInstance,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios';
import { clearAccessToken, getAccessToken, setAccessToken } from '../lib/authToken';
import type { paths } from '../types/api-contracts';
import { stringifyId } from '../lib/utils';
import type {
  User,
  ProspectWithConnectors,
  ProspectFilters,
  AIWorkflow,
  WorkflowTemplate,
  ApprovalRequest,
  AnalyticsOverview,
  CorporateWorkflowRun,
  CorporateWorkflowMetrics,
  IntegrationSet,
  TeamMember,
  APIResponse,
  PaginatedResponse,
  LoginForm,
  LoginRosterUser,
  ProspectImportForm,
  ApprovalDecisionForm,
  Message,
  Conversation,
  Agent,
  CommunicationHubFilters,
  AgentEvent,
  AgentEventFilters,
  AgentEventsSummary,
  AgentEventCreate,
  RegistrationRequest,
  CompanyRegistrationPayload,
  CompanyRegistrationDevPayload,
  CompanyRegistrationResponse,
  OrganizationProfile,
  RegistrationKeyListItem,
  RegistrationKeyResponse,
  RegistrationKeyDownloadPayload,
  CookieStatus,
  CookieOverview,
  CookieEvent,
  ScrapingPolicyUpdatePayload,
  OrganizationSearchResult,
  RedeemRegistrationResponse,
  OnboardingProgress,
  OnboardingNudgeResponse,
  ProviderHealthStatus,
  IntegrationHealthStatus,
  RegistrationOptions,
  EmailCampaign,
  EmailTemplate,
  EmailMetrics,
  MasterAddTeamMemberPayload,
} from '../types';

type Operation<Path extends keyof paths, Method extends keyof paths[Path]> = paths[Path][Method];
type SuccessResponse<Responses> =
  Responses extends { 200: infer Success }
    ? Success
    : Responses extends { '200': infer Success }
      ? Success
      : never;
type ExtractSuccessJson<Path extends keyof paths, Method extends keyof paths[Path]> =
  Operation<Path, Method> extends { responses: infer Responses }
    ? SuccessResponse<Responses> extends { content: infer Content }
      ? Content extends { 'application/json': infer Json }
        ? Json
        : never
      : never
    : never;

type ProspectListEnvelope = ExtractSuccessJson<'/api/prospects', 'get'>;
type AnalyticsOverviewEnvelope = ExtractSuccessJson<'/api/analytics/overview', 'get'>;
type FeatureFlagEnvelope = ExtractSuccessJson<'/api/feature-flags', 'get'>;
type HealthEnvelope = ExtractSuccessJson<'/api/health', 'get'>;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const toOptionalString = (value: unknown): string | undefined =>
  typeof value === 'string' ? value : undefined;

export interface CredentialSecretStatus {
  configured: boolean;
  masked?: string | null;
  vaultItemId?: string | null;
  lastRotatedAt?: string | null;
  createdByUserId?: string | null;
  label?: string;
  provider?: string;
  [key: string]: unknown;
}

export interface CredentialSettingsPayload {
  secrets: Record<string, CredentialSecretStatus>;
  integrations?: Record<string, unknown>;
  updated_at?: string;
  [key: string]: unknown;
}

export interface CredentialSecretUpdate {
  value: string;
}

export interface UpdateCredentialSettingsPayload {
  secrets?: Record<string, CredentialSecretUpdate>;
  [key: string]: unknown;
}

export interface IntegrationTestResult {
  integration: string;
  status: string;
  message?: string;
  config?: Record<string, unknown> | null;
  health?: Record<string, unknown> | null;
}

class APIService {
  private client: AxiosInstance;
  private refreshPromise: Promise<string | null> | null = null;

  private static resolveBaseUrl(): string | undefined {
    const explicitBase =
      process.env.NEXT_PUBLIC_API_URL ??
      process.env.API_URL ??
      process.env.NEXT_PUBLIC_SITE_URL ??
      process.env.SITE_URL;

    if (explicitBase) {
      return explicitBase;
    }

    if (typeof window !== 'undefined') {
      try {
        return window.location?.origin;
      } catch (error) {
        console.warn('[API] Failed to infer base URL from window location.', error);
      }
    }

    return undefined;
  }

  private static resolveDefaultOrgId(): string | undefined {
    const raw =
      process.env.NEXT_PUBLIC_DEFAULT_ORG_ID ??
      process.env.NEXT_PUBLIC_ORGANIZATION_ID ??
      process.env.NEXT_PUBLIC_TENANT_ID ??
      process.env.ORGANIZATION_ID ??
      process.env.TENANT_ID;
    if (typeof raw === 'string' && raw.trim().length > 0) {
      return raw.trim();
    }
    return undefined;
  }

  private toApiResponse<T>(response: AxiosResponse<unknown>): APIResponse<T> {
    const rawPayload = response.data ?? {};
    const payload: Record<string, unknown> =
      typeof rawPayload === 'object' && rawPayload !== null
        ? (rawPayload as Record<string, unknown>)
        : { data: rawPayload };

    const hasDataProperty = Object.prototype.hasOwnProperty.call(payload, 'data');
    const dataCandidate = hasDataProperty ? payload['data'] : payload;
    const data = dataCandidate as T;

    const errorValue = payload['error'];
    const detailValue = payload['detail'];
    const messageValue = payload['message'];

    const error =
      typeof errorValue === 'string'
        ? errorValue
        : typeof detailValue === 'string'
          ? detailValue
          : undefined;

    const message =
      typeof messageValue === 'string'
        ? messageValue
        : typeof detailValue === 'string' && detailValue !== error
          ? detailValue
          : undefined;

    const apiResponse: APIResponse<T> = {
      status: response.status,
    };

    if (data !== undefined) {
      apiResponse.data = data;
    }
    if (error !== undefined) {
      apiResponse.error = error;
    }
    if (message !== undefined) {
      apiResponse.message = message;
    }

    return apiResponse;
  }

  constructor() {
    const defaultBaseUrl = APIService.resolveBaseUrl();

    if (!defaultBaseUrl) {
      console.warn(
        '[API] No API base URL configured; falling back to relative requests. Configure NEXT_PUBLIC_API_URL for explicit targeting.'
      );
    }

    this.client = axios.create({
      ...(defaultBaseUrl ? { baseURL: defaultBaseUrl } : {}),
      timeout: 30000,
      withCredentials: true,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.client.interceptors.request.use(
      async (config: InternalAxiosRequestConfig) => {
        config.withCredentials = true;

        const headers =
          config.headers instanceof AxiosHeaders
            ? config.headers
            : new AxiosHeaders(config.headers ?? {});

        config.headers = headers;

        if (!headers.has('Accept')) {
          headers.set('Accept', 'application/json');
        }

        const isRefreshRequest = headers.get('X-Auth-Refresh') === '1';
        const isLoginRequest = headers.get('X-Auth-Login') === '1';
        const isLogoutRequest = headers.get('X-Auth-Logout') === '1';

        const token = getAccessToken();
        if (token && !headers.has('Authorization')) {
          headers.set('Authorization', `Bearer ${token}`);
        }

        return config;
      },
      (error) => Promise.reject(error),
    );

    this.client.interceptors.response.use(
      (response: AxiosResponse) => response,
      async (error: AxiosError) => {
        const status = error.response?.status ?? 0;
        const originalRequest = error.config as (InternalAxiosRequestConfig & { _retry?: boolean });

        let headers: AxiosHeaders | undefined;
        let isRefreshRequest = false;
        let isLoginRequest = false;
        let isLogoutRequest = false;

        if (originalRequest) {
          headers =
            originalRequest.headers instanceof AxiosHeaders
              ? originalRequest.headers
              : new AxiosHeaders(originalRequest.headers ?? {});

          originalRequest.headers = headers;

          isRefreshRequest = headers.get('X-Auth-Refresh') === '1';
          isLoginRequest = headers.get('X-Auth-Login') === '1';
          isLogoutRequest = headers.get('X-Auth-Logout') === '1';
        }

        const shouldHandle401 =
          status === 401 &&
          !isLoginRequest &&
          !isLogoutRequest &&
          !isRefreshRequest;

        let shouldLogoutAfter401 = shouldHandle401;

        if (shouldHandle401 && originalRequest && !originalRequest._retry) {
          originalRequest._retry = true;
          try {
            const refreshedToken = await this.refreshAccessToken();
            if (refreshedToken) {
              headers?.set('Authorization', `Bearer ${refreshedToken}`);
              return this.client(originalRequest);
            }
            shouldLogoutAfter401 = true;
          } catch (refreshError) {
            const refreshStatus =
              axios.isAxiosError(refreshError) ? refreshError.response?.status ?? 0 : 0;
            const authFailure = refreshStatus === 401 || refreshStatus === 403;
            if (!authFailure) {
              shouldLogoutAfter401 = false;
              console.warn('[API] Refresh token flow failed due to network/transient error', refreshError);
            } else {
              shouldLogoutAfter401 = true;
            }
          }
        }

        if (shouldHandle401 && shouldLogoutAfter401) {
          clearAccessToken();
          const isBrowser = typeof window !== 'undefined';
          const isJsdom =
            isBrowser &&
            typeof window.navigator !== 'undefined' &&
            /jsdom/i.test(window.navigator.userAgent ?? '');

          if (isBrowser && !isJsdom) {
            try {
              if (typeof window.location.assign === 'function') {
                window.location.assign('/login');
              } else if ('href' in window.location) {
                window.location.href = '/login';
              }
            } catch (navigationError) {
              console.warn('[API] Skipping redirect after 401 response due to navigation limitations.', navigationError);
            }
          }
        }

        return Promise.reject(error);
      },
    );
  }

  private async refreshAccessTokenInternal(): Promise<string | null> {
    try {
      const response = await this.client.post(
        '/api/auth/refresh',
        undefined,
        {
          headers: new AxiosHeaders({ 'X-Auth-Refresh': '1' }),
          withCredentials: true,
        },
      );
      const payload = response.data?.data ?? response.data;
      const accessToken = typeof payload?.access_token === 'string' ? payload.access_token : null;
      if (accessToken) {
        setAccessToken(accessToken);
        return accessToken;
      }
      clearAccessToken();
      return null;
    } catch (error) {
      const status = axios.isAxiosError(error) ? error.response?.status ?? 0 : 0;
      if (status === 401 || status === 403) {
        clearAccessToken();
        return null;
      }
      throw error;
    }
  }

  private async requestAccessTokenRefresh(force = false): Promise<string | null> {
    if (!force) {
      const existing = getAccessToken();
      if (existing) {
        return existing;
      }
    }

    if (!this.refreshPromise) {
      this.refreshPromise = this.refreshAccessTokenInternal().finally(() => {
        this.refreshPromise = null;
      });
    }

    return this.refreshPromise;
  }

  async refreshAccessToken(): Promise<string | null> {
    return this.requestAccessTokenRefresh(true);
  }

  async logout(): Promise<void> {
    try {
      await this.client.post(
        '/api/auth/logout',
        undefined,
        {
          headers: new AxiosHeaders({ 'X-Auth-Logout': '1' }),
          withCredentials: true,
        },
      );
    } catch (error) {
      console.warn('[API] Logout request failed', error);
    } finally {
      clearAccessToken();
    }
  }

  async deleteCurrentProfile(): Promise<APIResponse<{ message?: string }>> {
    const response = await this.client.delete('/api/auth/profile');
    const raw = response.data;
    const apiResponse: APIResponse<{ message?: string }> = {
      status: response.status,
    };

    if (raw && typeof raw === 'object') {
      const payload = raw as Record<string, unknown>;
      const envelope = (payload?.data ?? payload) as { message?: string };

      apiResponse.data = envelope;

      if (typeof payload.error === 'string') {
        apiResponse.error = payload.error;
      }
      if (typeof payload.message === 'string') {
        apiResponse.message = payload.message;
      } else if (typeof payload.detail === 'string') {
        apiResponse.message = payload.detail;
      }
    } else {
      apiResponse.data = {};
    }

    return apiResponse;
  }

  // Authentication
  async login(credentials: LoginForm): Promise<APIResponse<{ access_token: string; user: User | undefined; cookie_status?: string; accepted_terms?: boolean; organization_slug?: string }>> {
    const payload: Record<string, unknown> = {
      password: credentials.password,
    };
    if (typeof credentials.userId === 'number') {
      payload.user_id = credentials.userId;
    }
    if (credentials.email) {
      payload.email = credentials.email;
    }
    const defaultOrg = APIService.resolveDefaultOrgId();
    const response = await this.client.post('/api/auth/login', payload, {
      headers: new AxiosHeaders({
        'X-Auth-Login': '1',
        ...(defaultOrg ? { 'X-Organization-Id': defaultOrg } : {}),
      }),
      withCredentials: true,
    });
    const raw = response.data;
    const payloadData = raw?.data ?? raw;
    const accessToken = payloadData?.access_token ?? payloadData?.token;
    return {
      status: response.status,
      data: {
        access_token: accessToken,
        user: payloadData?.user,
        cookie_status: payloadData?.cookie_status,
        accepted_terms: payloadData?.accepted_terms,
        organization_slug: payloadData?.organization_slug,
      },
      error: raw?.error,
      message: raw?.message,
    };
  }

  async requestPasswordReset(email: string, organizationSlug?: string): Promise<APIResponse<{ message: string }>> {
    const body: Record<string, string> = { email };
    if (organizationSlug) {
      body.organization_slug = organizationSlug;
    }
    const response = await this.client.post('/api/auth/forgot-password', body);
    return this.toApiResponse<{ message: string }>(response);
  }

  async addTeamMemberWithMaster(
    payload: MasterAddTeamMemberPayload,
  ): Promise<APIResponse<{ success: boolean; team_member: { name: string; email: string }; user_id: number }>> {
    const response = await this.client.post('/api/auth/master/add-team-member', payload);
    return this.toApiResponse(response);
  }

  async getLoginRoster(): Promise<APIResponse<LoginRosterUser[]>> {
    const defaultOrg = APIService.resolveDefaultOrgId();
    const response = await this.client.get('/api/auth/login/roster', {
      headers: new AxiosHeaders({
        ...(defaultOrg ? { 'X-Organization-Id': defaultOrg } : {}),
      }),
      withCredentials: true,
    });
    const raw = response.data;
    const records = Array.isArray(raw?.users)
      ? raw.users.filter((item: unknown): item is Record<string, unknown> => typeof item === 'object' && item !== null)
      : [];
    const users: LoginRosterUser[] = records.map((user: Record<string, unknown>) => {
      const idValue = user['id'];
      const numericId =
        typeof idValue === 'number'
          ? idValue
          : typeof idValue === 'string'
            ? Number.parseInt(idValue, 10)
            : null;

      const firstName = typeof user['first_name'] === 'string' ? (user['first_name'] as string) : null;
      const lastName = typeof user['last_name'] === 'string' ? (user['last_name'] as string) : null;
      const displayNameSource =
        typeof user['display_name'] === 'string'
          ? (user['display_name'] as string)
          : [firstName, lastName].filter(Boolean).join(' ');

      const lastLoginAt =
        typeof user['last_login_at'] === 'string' ? (user['last_login_at'] as string) : null;

      const resolvedId =
        typeof numericId === 'number' && Number.isFinite(numericId) ? numericId : 0;

      return {
        id: resolvedId,
        displayName: displayNameSource && displayNameSource.trim().length > 0
          ? displayNameSource
          : 'Tallwave Teammate',
        firstName,
        lastName,
        lastLoginAt,
      };
    });
    return {
      status: response.status,
      data: users,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async registerWithKey(payload: RegistrationRequest): Promise<APIResponse<RedeemRegistrationResponse>> {
    const response = await this.client.post('/api/company/registration-keys/redeem', {
      registration_key: payload.registrationKey,
      email: payload.email,
      first_name: payload.firstName,
      last_name: payload.lastName,
      password: payload.password,
      organization_slug: payload.organizationSlug,
    });
    const raw = response.data;
    const payloadData = raw?.data ?? raw;
    return {
      status: response.status,
      data: payloadData,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async registerCompany(payload: CompanyRegistrationPayload): Promise<APIResponse<CompanyRegistrationResponse>> {
    const response = await this.client.post('/api/company/register', {
      company_name: payload.companyName,
      domain: payload.domain,
      slug: payload.slug,
      company_industry: payload.companyIndustry,
      seat_count: payload.seatCount,
      plan: {
        tier: payload.plan.tier,
        price_id: payload.plan.priceId,
        seats: payload.plan.seats,
      },
      billing: {
        payment_method_id: payload.billing.paymentMethodId,
        email: payload.billing.email,
        tax_id: payload.billing.taxId,
        address: {
          line1: payload.billing.address.line1,
          city: payload.billing.address.city,
          state: payload.billing.address.state,
          postal_code: payload.billing.address.postalCode,
          country: payload.billing.address.country,
        },
        additional_notes: payload.billing.notes,
      },
      admin: {
        email: payload.admin.email,
        first_name: payload.admin.firstName,
        last_name: payload.admin.lastName,
        password: payload.admin.password,
        job_title: payload.admin.jobTitle,
      },
    });
    const raw = response.data;
    const payloadData = raw?.data ?? raw;
    return {
      status: response.status,
      data: payloadData,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async registerCompanyDev(
    payload: CompanyRegistrationDevPayload
  ): Promise<APIResponse<CompanyRegistrationResponse>> {
    const response = await this.client.post('/api/company/register/dev', {
      company_name: payload.companyName,
      domain: payload.domain,
      slug: payload.slug,
      plan_tier: payload.planTier,
      seat_count: payload.seatCount,
      notes: payload.notes,
      admin: {
        email: payload.admin.email,
        first_name: payload.admin.firstName,
        last_name: payload.admin.lastName,
        password: payload.admin.password,
        job_title: payload.admin.jobTitle,
      },
    });
    const raw = response.data;
    const payloadData = raw?.data ?? raw;
    return {
      status: response.status,
      data: payloadData,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getRegistrationOptions(): Promise<APIResponse<RegistrationOptions>> {
    const response = await this.client.get('/api/company/register/options');
    const raw = response.data;
    const payload = raw?.data ?? raw ?? {};
    const options: RegistrationOptions = {
      industries: Array.isArray(payload.industries)
        ? payload.industries.map((entry: unknown) => String(entry))
        : [],
      company_sizes: Array.isArray(payload.company_sizes)
        ? payload.company_sizes.map((entry: unknown) => String(entry))
        : [],
      developer_mode: Boolean(payload.developer_mode),
      seat_policy: typeof payload.seat_policy === 'object' && payload.seat_policy !== null
        ? {
            type: String(payload.seat_policy.type ?? 'unlimited'),
            description:
              typeof payload.seat_policy.description === 'string'
                ? payload.seat_policy.description
                : undefined,
            maxSeats:
              typeof payload.seat_policy.max_seats === 'number'
                ? payload.seat_policy.max_seats
                : payload.seat_policy.maxSeats ?? null,
          }
        : { type: 'unlimited', description: 'Tallwave users receive unlimited access.', maxSeats: null },
    };
    return {
      status: response.status,
      data: options,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getCurrentUser(): Promise<APIResponse<User>> {
    const response = await this.client.get('/api/auth/me');
    const raw = response.data;
    const payload = raw?.data ?? raw?.user ?? raw;
    return {
      status: response.status,
      data: payload,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getOrganizationProfile(): Promise<APIResponse<OrganizationProfile>> {
    const response = await this.client.get('/api/company/organizations/me');
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getOnboardingProgress(organizationId: string | number): Promise<APIResponse<OnboardingProgress>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/company/organizations/${orgKey}/onboarding/progress`);
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getProviderHealth(): Promise<APIResponse<Record<string, ProviderHealthStatus>>> {
    const response = await this.client.get('/api/settings/service-health');
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data?.providers ?? raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getIntegrationHealth(): Promise<APIResponse<Record<string, IntegrationHealthStatus>>> {
    const response = await this.client.get('/api/company/integrations/health');
    const raw = response.data;
    const payload =
      ((raw?.integrations ?? raw?.data?.integrations ?? raw?.data ?? {}) as Record<
        string,
        IntegrationHealthStatus
      >) || {};
    return {
      status: response.status,
      data: payload,
      error: raw?.error,
      message: raw?.message ?? raw?.detail,
    };
  }

  async sendOnboardingReminder(
    organizationId: string | number,
    payload?: { memberIds?: number[]; note?: string }
  ): Promise<APIResponse<OnboardingNudgeResponse>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post(
      `/api/company/organizations/${orgKey}/onboarding/nudge`,
      payload ?? {}
    );
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getTenantIntegrations(tenantId: string | number): Promise<APIResponse<CredentialSettingsPayload>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const response = await this.client.get(
      `/api/admin/tenants/${encodeURIComponent(tenantKey)}/settings/credentials`
    );
    const raw = response.data;
    const payload = (raw?.data ?? raw ?? {}) as CredentialSettingsPayload;
    if (!payload.secrets) {
      payload.secrets = {};
    }
    if (!payload.integrations) {
      payload.integrations = {};
    }
    return {
      status: response.status,
      data: payload,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async setTenantIntegrations(
    tenantId: string | number,
    settings: UpdateCredentialSettingsPayload
  ): Promise<APIResponse<CredentialSettingsPayload>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const requestBody: UpdateCredentialSettingsPayload = settings ?? {};
    const response = await this.client.put(
      `/api/admin/tenants/${encodeURIComponent(tenantKey)}/settings/credentials`,
      requestBody,
    );
    const raw = response.data;
    const payload = (raw?.data ?? raw ?? {}) as CredentialSettingsPayload;
    if (!payload.secrets) {
      payload.secrets = {};
    }
    if (!payload.integrations) {
      payload.integrations = {};
    }
    const resolvedMessage = raw?.message ?? (payload as { message?: string }).message ?? raw?.detail;
    return {
      status: response.status,
      data: payload,
      error: raw?.error,
      message: resolvedMessage,
    };
  }

  async testIntegrationConnection(
    integrationId: string
  ): Promise<APIResponse<IntegrationTestResult>> {
    const response = await this.client.post('/api/company/integrations/test', {
      integrationId,
    });
    return this.toApiResponse<IntegrationTestResult>(response);
  }

  async getCredentialSecretValue(
    secretKey: string,
    tenantId?: string | number,
  ): Promise<APIResponse<{ value: string }>> {
    const encodedKey = encodeURIComponent(secretKey);
    let response;

    if (tenantId !== undefined && tenantId !== null) {
      const tenantKey = stringifyId(tenantId);
      if (!tenantKey) {
        throw new Error('tenantId is required when provided');
      }
      response = await this.client.get(
        `/api/admin/tenants/${encodeURIComponent(tenantKey)}/settings/credentials/${encodedKey}/value`
      );
    } else {
      response = await this.client.get(`/api/settings/credentials/${encodedKey}/value`);
    }

    const raw = response.data;
    const payload = raw?.data ?? raw;

    return {
      status: response.status,
      data: payload,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getOrganizationBySlug(slug: string): Promise<APIResponse<OrganizationProfile>> {
    const response = await this.client.get(`/api/company/organizations/by-slug/${encodeURIComponent(slug)}`);
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async acceptTerms(): Promise<APIResponse<{ status: string; accepted_at: string }>> {
    const response = await this.client.post('/api/user/accept-terms');
    const raw = response.data;
    const payloadData = raw?.data ?? raw;
    return {
      status: response.status,
      data: payloadData,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async searchOrganizations(term: string): Promise<APIResponse<OrganizationSearchResult[]>> {
    const response = await this.client.get('/api/company/organizations/search', {
      params: { term },
    });
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getRegistrationKeys(organizationId: string | number): Promise<APIResponse<RegistrationKeyListItem[]>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/company/organizations/${orgKey}/registration-keys`);
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async generateRegistrationKeys(
    organizationId: string | number,
    count: number
  ): Promise<APIResponse<RegistrationKeyResponse[]>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post(
      `/api/company/organizations/${orgKey}/registration-keys`,
      { count }
    );
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async downloadRegistrationKey(
    deliveryToken: string
  ): Promise<APIResponse<RegistrationKeyDownloadPayload>> {
    const response = await this.client.get(`/api/company/registration-keys/${deliveryToken}`);
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async releaseRegistrationKey(
    organizationId: string | number,
    keyId: number
  ): Promise<APIResponse<{ status: string }>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post(
      `/api/company/organizations/${orgKey}/registration-keys/${keyId}/release`
    );
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async requestSeatUpgrade(
    organizationId: string | number,
    payload: { seats?: number; notes?: string; requesterEmail?: string }
  ): Promise<
    APIResponse<{
      status: string;
      requested_at: string;
      seat_requests_recorded: number;
      alert_failures?: string[];
    }>
  > {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post(
      `/api/company/organizations/${orgKey}/seats/request`,
      {
        seats: payload.seats,
        notes: payload.notes,
        requester_email: payload.requesterEmail,
      }
    );
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getCookieJarStatus(organizationId: string | number): Promise<APIResponse<CookieStatus>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/company/organizations/${orgKey}/cookie-jar/me`);
    const raw = response.data;
    const payload = raw?.data ?? raw;
    return {
      status: response.status,
      data: payload,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async uploadCookieJar(
    organizationId: string | number,
    payload:
      | { li_at: string; jsessionid?: string; user_agent?: string; label?: string | null }  // Plain (legacy)
      | { encrypted_payload: string; encryption_key: string; iv: string }  // Encrypted (new)
  ): Promise<APIResponse<CookieStatus>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post(
      `/api/company/organizations/${orgKey}/cookie-jar`,
      payload
    );
    const raw = response.data;
    const data = raw?.data ?? raw;
    return {
      status: response.status,
      data,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async listCookieStatuses(organizationId: string | number): Promise<APIResponse<CookieStatus[]>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/company/organizations/${orgKey}/cookie-jar`);
    const raw = response.data;
    const data = raw?.data ?? raw;
    return {
      status: response.status,
      data,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async revalidateCookieJar(
    organizationId: string | number,
    jarId: number
  ): Promise<APIResponse<CookieStatus>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post(
      `/api/company/organizations/${orgKey}/cookie-jar/${jarId}/revalidate`
    );
    const raw = response.data;
    const data = raw?.data ?? raw;
    return {
      status: response.status,
      data,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getCookieOverview(organizationId: string | number): Promise<APIResponse<CookieOverview>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/company/organizations/${orgKey}/cookie-jar/overview`);
    const raw = response.data;
    const data = raw?.data ?? raw;
    return {
      status: response.status,
      data,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async listCookieEvents(
    organizationId: string | number,
    jarId: number
  ): Promise<APIResponse<CookieEvent[]>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(
      `/api/company/organizations/${orgKey}/cookie-jar/${jarId}/events`
    );
    const raw = response.data;
    const data = raw?.data ?? raw ?? [];
    return {
      status: response.status,
      data,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async updateScrapingPolicy(
    organizationId: string | number,
    payload: ScrapingPolicyUpdatePayload
  ): Promise<APIResponse<CookieOverview>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.patch(
      `/api/company/organizations/${orgKey}/scraping-policy`,
      payload
    );
    const raw = response.data;
    const data = raw?.data ?? raw;
    return {
      status: response.status,
      data,
      error: raw?.error,
      message: raw?.message,
    };
  }

  // Health Check
  async getHealthCheck(): Promise<HealthEnvelope> {
    const response = await this.client.get('/api/health');
    return response.data as HealthEnvelope;
  }

  // Analytics
  async getAnalyticsOverview(
    organizationId: string | number,
    days: number = 30
  ): Promise<APIResponse<AnalyticsOverview>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const params = new URLSearchParams({
      organization_id: orgKey,
      days: days.toString(),
    });
    const response = await this.client.get(`/api/analytics/overview?${params.toString()}`);
    const payload = response.data as AnalyticsOverviewEnvelope;
    return {
      status: response.status,
      data: (payload.data as unknown as AnalyticsOverview) ?? ({} as AnalyticsOverview),
      ...(payload?.message && { message: payload.message }),
    };
  }

  async getFeatureFlags(): Promise<FeatureFlagEnvelope> {
    const response = await this.client.get('/api/feature-flags');
    return response.data as FeatureFlagEnvelope;
  }

  // Prospects
  async getProspects(
    filters: ProspectFilters = {},
    organizationId?: string | number,
  ): Promise<ProspectWithConnectors[]> {
    const params = new URLSearchParams();

    if (filters.search) params.append('search', filters.search);
    if (filters.company) params.append('company', filters.company);
    if (Array.isArray(filters.status) && filters.status.length > 0) {
      filters.status.forEach((status) => params.append('status', status));
    }
    if (Array.isArray(filters.priority) && filters.priority.length > 0) {
      filters.priority.forEach((priority) => params.append('priority', priority));
    }
    if (filters.hasConnectors !== undefined) {
      params.append('has_connectors', String(filters.hasConnectors));
    }
    if (filters.dateRange?.start) params.append('start_date', filters.dateRange.start);
    if (filters.dateRange?.end) params.append('end_date', filters.dateRange.end);
    if (
      organizationId !== undefined &&
      organizationId !== null &&
      String(organizationId).toLowerCase() !== 'null'
    ) {
      params.append('organization_id', String(organizationId));
    }

    const query = params.toString();
    const url = query ? `/api/prospects?${query}` : '/api/prospects';
    const response = await this.client.get(url);
    const payload = response.data as ProspectListEnvelope;

    if (payload?.data && Array.isArray(payload.data)) {
      return payload.data as unknown as ProspectWithConnectors[];
    }

    return Array.isArray(payload) ? (payload as unknown as ProspectWithConnectors[]) : [];
  }

  async importProspects(data: ProspectImportForm): Promise<APIResponse<{ job_id: string }>> {
    const response = await this.client.post('/api/prospects/import', data);
    return this.toApiResponse<{ job_id: string }>(response);
  }

  async reprocessProspect(prospectId: number): Promise<APIResponse<{ job_id: string }>> {
    const response = await this.client.post(`/api/prospects/${prospectId}/reprocess`);
    return this.toApiResponse<{ job_id: string }>(response);
  }

  async createIntroduction(payload: { prospectId: number; teamMemberId: number; message: string }): Promise<APIResponse<{ success: boolean }>> {
    const response = await this.client.post('/api/introductions/create-introduction', {
      prospect_id: payload.prospectId,
      team_member_id: payload.teamMemberId,
      introduction_message: payload.message,
    });
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  // September 2025 AI Workflows
  async getWorkflowTemplates(tenantId: string | number, category?: string): Promise<APIResponse<{ templates: WorkflowTemplate[] }>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const params = new URLSearchParams({ tenant_id: tenantKey });
    if (category) params.append('category', category);
    const response = await this.client.get(`/api/workflows/templates?${params.toString()}`);
    return this.toApiResponse<{ templates: WorkflowTemplate[] }>(response);
  }

  async getCorporateWorkflows(
    tenantId: string | number,
    status?: string,
    limit: number = 50
  ): Promise<APIResponse<{ workflows: CorporateWorkflowRun[]; total_count?: number }>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const params = new URLSearchParams({
      tenant_id: tenantKey,
      limit: limit.toString(),
    });
    if (status) params.append('status', status);

    const response = await this.client.get(`/api/workflows/corporate?${params.toString()}`);
    return this.toApiResponse<{ workflows: CorporateWorkflowRun[]; total_count?: number }>(response);
  }

  async startCorporateWorkflow(
    tenantId: string | number,
    file?: File,
    options: { priority?: 'low' | 'normal' | 'high' | 'critical'; metadata?: Record<string, unknown>; companyList?: string } = {}
  ): Promise<APIResponse<CorporateWorkflowRun>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const params = new URLSearchParams({
      tenant_id: tenantKey,
    });

    const formData = new FormData();
    formData.append('priority', options.priority ?? 'normal');

    if (options.metadata && Object.keys(options.metadata).length > 0) {
      formData.append('metadata', JSON.stringify(options.metadata));
    }

    if (options.companyList) {
      formData.append('company_list', options.companyList);
    }

    if (file) {
      formData.append('file', file);
    }

    const response = await this.client.post(
      `/api/workflows/corporate/start?${params.toString()}`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return this.toApiResponse<CorporateWorkflowRun>(response);
  }

  async getActiveWorkflows(tenantId: string | number): Promise<APIResponse<{ workflows: AIWorkflow[] }>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const params = new URLSearchParams({ tenant_id: tenantKey });
    const response = await this.client.get(`/api/workflows/active?${params.toString()}`);
    return this.toApiResponse<{ workflows: AIWorkflow[] }>(response);
  }

  async startWorkflow(
    tenantId: string | number,
    execution: {
      workflow_type?: string;
      template_id?: string;
      name?: string;
      parameters?: Record<string, unknown>;
      context_data?: Record<string, unknown>;
      priority?: string;
      schedule?: string;
    }
  ): Promise<APIResponse<{ workflow_id: string; execution: CorporateWorkflowRun }>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const workflowType = (execution.workflow_type ?? 'automated_outreach').toLowerCase();
    const parameters: Record<string, unknown> = {
      ...(execution.parameters ?? {}),
      tenant_id: tenantKey,
    };

    if (execution.template_id) {
      parameters.template_id = execution.template_id;
    }

    if (execution.name) {
      parameters.name = execution.name;
    }

    if (execution.context_data) {
      parameters.context_data = execution.context_data;
    }

    if (execution.priority) {
      parameters.priority = execution.priority;
    }

    if (execution.schedule) {
      parameters.schedule = execution.schedule;
    }

    const payload: Record<string, unknown> = {
      workflow_type: workflowType,
      tenant_id: tenantKey,
      parameters,
    };

    if (execution.template_id) {
      payload.template_id = execution.template_id;
    }

    if (execution.name) {
      payload.name = execution.name;
    }

    if (execution.schedule) {
      payload.schedule = execution.schedule;
    }

    const response = await this.client.post('/api/company/workflows/start', payload);
    return this.toApiResponse<{ workflow_id: string; execution: CorporateWorkflowRun }>(response);
  }

  async retryCorporateWorkflow(tenantId: string | number, workflowId: string): Promise<APIResponse<CorporateWorkflowRun>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const params = new URLSearchParams({ tenant_id: tenantKey });
    const response = await this.client.post(
      `/api/workflows/corporate/${workflowId}/retry?${params.toString()}`
    );
    return this.toApiResponse<CorporateWorkflowRun>(response);
  }

  async getCorporateWorkflowMetrics(
    tenantId: string | number,
    days: number = 30
  ): Promise<APIResponse<CorporateWorkflowMetrics>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const params = new URLSearchParams({
      tenant_id: tenantKey,
      days: days.toString(),
    });
    const response = await this.client.get(
      `/api/workflows/corporate/metrics/summary?${params.toString()}`
    );
    return this.toApiResponse<CorporateWorkflowMetrics>(response);
  }

  async stopWorkflow(
    tenantId: string | number,
    workflowId: string,
    reason?: string
  ): Promise<APIResponse<{ workflow_id: string; reason?: string }>> {
    const tenantKey = stringifyId(tenantId);
    if (!tenantKey) {
      throw new Error('tenantId is required');
    }
    const payload: Record<string, unknown> = { tenant_id: tenantKey };
    if (reason) {
      payload.reason = reason;
    }

    const response = await this.client.post(`/api/company/workflows/${workflowId}/stop`, payload);
    return this.toApiResponse<{ workflow_id: string; reason?: string }>(response);
  }

  // Human-in-the-Loop Approvals
  async getApprovalRequests(params: {
    tenantId: number | string;
    status?: string;
    page?: number;
    limit?: number;
  }): Promise<PaginatedResponse<ApprovalRequest>> {
    const { tenantId, status, page = 1, limit = 20 } = params;

    const query = new URLSearchParams({
      tenant_id: String(tenantId),
      page: page.toString(),
      limit: limit.toString(),
    });
    if (status) query.append('status', status);

    const response = await this.client.get(`/api/approvals?${query.toString()}`);
    const raw = response.data;
    const rawApprovals = Array.isArray(raw?.data)
      ? raw.data
      : Array.isArray(raw?.approvals)
        ? raw.approvals
        : [];
    const source = rawApprovals.filter((entry: unknown): entry is Record<string, unknown> =>
      isRecord(entry)
    );

    const approvals: ApprovalRequest[] = source.map((item: Record<string, unknown>) => {
      const riskScoreValue = item['risk_score'];
      const contextValue = item['context'];
      const tenantValue = item['tenant_id'];
      const riskScore =
        typeof riskScoreValue === 'number'
          ? riskScoreValue
          : riskScoreValue !== undefined && riskScoreValue !== null && !Number.isNaN(Number(riskScoreValue))
            ? Number(riskScoreValue)
            : undefined;

      return {
        approval_id: toOptionalString(item['approval_id']) ?? String(item['approval_id'] ?? ''),
        workflow_id: toOptionalString(item['workflow_id']) ?? String(item['workflow_id'] ?? ''),
        action: toOptionalString(item['action']) ?? 'approval_required',
        description: toOptionalString(item['description']) ?? '',
        status: toOptionalString(item['status']) ?? 'pending',
        priority: toOptionalString(item['priority']) ?? 'medium',
        context: isRecord(contextValue) ? contextValue : {},
        risk_score: riskScore,
        requested_at: toOptionalString(item['requested_at']) ?? '',
        timeout_at: toOptionalString(item['timeout_at']) ?? '',
        approver_id: toOptionalString(item['approver_id']) ?? undefined,
        approval_comments: toOptionalString(item['approval_comments']) ?? undefined,
        rejection_reason: toOptionalString(item['rejection_reason']) ?? undefined,
        tenant_id:
          typeof tenantValue === 'number' || typeof tenantValue === 'string'
            ? (tenantValue as number | string)
            : undefined,
      };
    });

    const pagination = raw?.pagination ?? {
      page,
      limit,
      total: raw?.total ?? approvals.length,
      pages: raw?.pagination?.pages ?? Math.max(1, Math.ceil((raw?.total ?? approvals.length) / limit)),
    };

    return {
      data: approvals,
      pagination,
    };
  }

  async getApprovalRequest(approvalId: string): Promise<APIResponse<ApprovalRequest>> {
    const response = await this.client.get(`/api/approvals/${approvalId}`);
    return this.toApiResponse<ApprovalRequest>(response);
  }

  async makeApprovalDecision(
    approvalId: string,
    decision: ApprovalDecisionForm,
    approverId: number | string
  ): Promise<APIResponse<unknown>> {
    const payload = {
      status: decision.decision === 'approve' ? 'approved' : 'rejected',
      comments: decision.notes,
      approver_id: String(approverId),
    };
    const response = await this.client.post(`/api/approvals/${approvalId}/respond`, payload);
    return this.toApiResponse<unknown>(response);
  }

  async getApprovalStats(tenantId: number | string): Promise<APIResponse<unknown>> {
    const params = new URLSearchParams({ tenant_id: String(tenantId) });
    const response = await this.client.get(`/api/approvals/stats?${params.toString()}`);
    return this.toApiResponse<unknown>(response);
  }

  // Team Members
  async getTeamMembers(organizationId: string | number): Promise<APIResponse<TeamMember[]>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/company/organizations/${orgKey}/team-members`);
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async updateTeamMember(
    organizationId: string | number,
    memberId: number,
    data: { role?: 'admin' | 'user'; status?: string }
  ): Promise<APIResponse<TeamMember>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.patch(
      `/api/company/organizations/${orgKey}/team-members/${memberId}`,
      data
    );
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async resetTeamMemberPassword(
    organizationId: string | number,
    memberId: number
  ): Promise<APIResponse<{ token: string; expires_at: string; reset_url?: string }>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post(
      `/api/company/organizations/${orgKey}/team-members/${memberId}/reset-password`
    );
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.data ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  // Integration Settings
  async getIntegrationSet(): Promise<APIResponse<IntegrationSet>> {
    const response = await this.client.get('/api/integration-set');
    return this.toApiResponse<IntegrationSet>(response);
  }

  async updateIntegrationSet(data: Partial<IntegrationSet>): Promise<APIResponse<IntegrationSet>> {
    const response = await this.client.post('/api/integration-set', data);
    return this.toApiResponse<IntegrationSet>(response);
  }

  async getIntegrationHealthSummary(): Promise<APIResponse<Record<string, unknown>>> {
    const response = await this.client.get('/api/company/integrations/health');
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.integrations ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  async getIntegrationConfigSummary(): Promise<APIResponse<Record<string, unknown>>> {
    const response = await this.client.get('/api/company/integrations/config');
    const raw = response.data;
    return {
      status: response.status,
      data: raw?.configurations ?? raw,
      error: raw?.error,
      message: raw?.message,
    };
  }

  // Email Management
  async scheduleEmails(data: {
    prospect_ids: number[];
    template_id: number;
  }): Promise<APIResponse<{ job_id: string }>> {
    const response = await this.client.post('/api/emails/schedule', data);
    return this.toApiResponse<{ job_id: string }>(response);
  }

  async getPendingEmailApprovals(): Promise<APIResponse<unknown[]>> {
    const response = await this.client.get('/api/emails/pending-approval');
    return this.toApiResponse<unknown[]>(response);
  }

  // Admin
  async getSystemStats(): Promise<APIResponse<unknown>> {
    const response = await this.client.get('/api/admin/system-stats');
    return this.toApiResponse<unknown>(response);
  }

  // File uploads
  async uploadFile(file: File, endpoint: string): Promise<APIResponse<unknown>> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await this.client.post(endpoint, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return this.toApiResponse<unknown>(response);
  }

  // Communication Hub - Messages
  async getCommunicationMessages(filters?: {
    conversation_id?: string;
    sender_type?: 'human' | 'ai';
    message_type?: 'text' | 'approval_request';
    organization_id?: string | number;
    page?: number;
    limit?: number;
  }): Promise<PaginatedResponse<Message>> {
    const params = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          if (key === 'organization_id') {
            const idValue = stringifyId(value);
            if (idValue) {
              params.append(key, idValue);
            }
          } else {
            params.append(key, value.toString());
          }
        }
      });
    }

    const response = await this.client.get(`/api/v1/communication-hub/messages?${params}`);
    return response.data;
  }

  async sendCommunicationMessage(data: {
    conversation_id: string;
    content: string;
    message_type?: 'text' | 'approval_request';
    organization_id: string | number;
    metadata?: Record<string, unknown>;
  }): Promise<APIResponse<Message>> {
    const payload = {
      ...data,
      organization_id: stringifyId(data.organization_id) ?? String(data.organization_id),
    };
    const response = await this.client.post('/api/v1/communication-hub/messages', payload);
    return this.toApiResponse<Message>(response);
  }

  // Communication Hub - Conversations
  async getCommunicationConversations(filters?: CommunicationHubFilters): Promise<APIResponse<Conversation[]>> {
    const params = new URLSearchParams();
    const appendParam = (key: string, value: unknown): void => {
      if (value === undefined || value === null) {
        return;
      }

      if (Array.isArray(value)) {
        value.forEach((item) => appendParam(`${key}[]`, item));
        return;
      }

      if (value instanceof Date) {
        params.append(key, value.toISOString());
        return;
      }

      if (typeof value === 'object') {
        Object.entries(value as Record<string, unknown>).forEach(([nestedKey, nestedValue]) => {
          appendParam(`${key}[${nestedKey}]`, nestedValue);
        });
        return;
      }

      if (typeof value === 'boolean') {
        params.append(key, value ? 'true' : 'false');
        return;
      }

      if (key === 'organization_id') {
        const idValue = stringifyId(value as string | number | null | undefined);
        if (idValue) {
          params.append(key, idValue);
        }
        return;
      }

      params.append(key, String(value));
    };

    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        appendParam(key, value);
      });
    }

    const response = await this.client.get(`/api/v1/communication-hub/conversations?${params}`);
    return this.toApiResponse<Conversation[]>(response);
  }

  async createCommunicationConversation(data: {
    title: string;
    participants: Array<{
      id: string;
      name: string;
      type: 'human' | 'ai';
    }>;
    status: 'active';
    priority: 'low' | 'medium' | 'high';
    organization_id: string | number;
    metadata?: Record<string, unknown>;
  }): Promise<APIResponse<Conversation>> {
    const payload = {
      ...data,
      organization_id: stringifyId(data.organization_id) ?? String(data.organization_id),
    };
    const response = await this.client.post('/api/v1/communication-hub/conversations', payload);
    return this.toApiResponse<Conversation>(response);
  }

  // Communication Hub - Agents
  async getCommunicationAgents(filters?: {
    organization_id?: string | number;
    status?: 'active' | 'paused' | 'error' | 'idle' | 'configuring';
    agent_type?: string;
  }): Promise<APIResponse<Agent[]>> {
    const params = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          if (key === 'organization_id') {
            const idValue = stringifyId(value);
            if (idValue) {
              params.append(key, idValue);
            }
          } else {
            params.append(key, value.toString());
          }
        }
      });
    }

    const response = await this.client.get(`/api/v1/communication-hub/agents?${params}`);
    return this.toApiResponse<Agent[]>(response);
  }

  // Communication Hub - Approvals
  async processCommunicationApproval(
    messageId: string,
    decision: 'approve' | 'reject',
    notes?: string,
    metadata?: Record<string, unknown>
  ): Promise<APIResponse<unknown>> {
    const response = await this.client.post('/api/v1/communication-hub/approvals', {
      message_id: messageId,
      decision,
      notes,
      metadata,
    });
    return this.toApiResponse<unknown>(response);
  }

  // Communication Hub - Webhooks
  async registerCommunicationWebhook(data: {
    event_type: string;
    url: string;
    organization_id: number;
    secret?: string;
  }): Promise<APIResponse<unknown>> {
    const response = await this.client.post('/api/v1/communication-hub/webhooks', data);
    return this.toApiResponse<unknown>(response);
  }

  // Email Management
  async getEmailCampaigns(organizationId: string | number): Promise<APIResponse<EmailCampaign[]>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/email/campaigns?organization_id=${encodeURIComponent(orgKey)}`);
    return this.toApiResponse<EmailCampaign[]>(response);
  }

  async getEmailTemplates(organizationId: string | number): Promise<APIResponse<EmailTemplate[]>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/email/templates?organization_id=${encodeURIComponent(orgKey)}`);
    return this.toApiResponse<EmailTemplate[]>(response);
  }

  async getEmailMetrics(organizationId: string | number): Promise<APIResponse<EmailMetrics>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/email/metrics?organization_id=${encodeURIComponent(orgKey)}`);
    return this.toApiResponse<EmailMetrics>(response);
  }

  async createEmailCampaign(organizationId: string | number, data: Record<string, unknown>): Promise<APIResponse<EmailCampaign>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post('/api/email/campaigns', { ...data, organization_id: orgKey });
    return this.toApiResponse<EmailCampaign>(response);
  }

  async createEmailTemplate(organizationId: string | number, data: Record<string, unknown>): Promise<APIResponse<EmailTemplate>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.post('/api/email/templates', { ...data, organization_id: orgKey });
    return this.toApiResponse<EmailTemplate>(response);
  }

  async pauseEmailCampaign(campaignId: string): Promise<APIResponse<unknown>> {
    const response = await this.client.put(`/api/email/campaigns/${campaignId}/pause`);
    return this.toApiResponse<unknown>(response);
  }

  async deleteEmailTemplate(templateId: string): Promise<APIResponse<unknown>> {
    const response = await this.client.delete(`/api/email/templates/${templateId}`);
    return this.toApiResponse<unknown>(response);
  }

  // Agent Events API
  async getAgentEvents(filters?: AgentEventFilters): Promise<APIResponse<AgentEvent[]>> {
    const params = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined) {
          params.append(key, value.toString());
        }
      });
    }

    const response = await this.client.get(`/api/agent-events?${params}`);
    return this.toApiResponse<AgentEvent[]>(response);
  }

  async getAgentEventsSummary(organizationId: string | number): Promise<APIResponse<AgentEventsSummary>> {
    const orgKey = stringifyId(organizationId);
    if (!orgKey) {
      throw new Error('organizationId is required');
    }
    const response = await this.client.get(`/api/agent-events/summary?organization_id=${encodeURIComponent(orgKey)}`);
    return this.toApiResponse<AgentEventsSummary>(response);
  }

  async createAgentEvent(eventData: AgentEventCreate): Promise<APIResponse<AgentEvent>> {
    const response = await this.client.post('/api/agent-events', eventData);
    return this.toApiResponse<AgentEvent>(response);
  }

  async getAgentEvent(eventId: string): Promise<APIResponse<AgentEvent>> {
    const response = await this.client.get(`/api/agent-events/${eventId}`);
    return this.toApiResponse<AgentEvent>(response);
  }

  // Generic HTTP methods for direct API calls
  async get<T = unknown>(url: string): Promise<APIResponse<T>> {
    const response = await this.client.get(url);
    return this.toApiResponse<T>(response);
  }

  async put<T = unknown>(url: string, data?: unknown): Promise<APIResponse<T>> {
    const response = await this.client.put(url, data);
    return this.toApiResponse<T>(response);
  }

  async post<T = unknown>(url: string, data?: unknown): Promise<APIResponse<T>> {
    const response = await this.client.post(url, data);
    return this.toApiResponse<T>(response);
  }

  async delete<T = unknown>(url: string): Promise<APIResponse<T>> {
    const response = await this.client.delete(url);
    return this.toApiResponse<T>(response);
  }

  // Authentication validation
  async validateAuth(): Promise<boolean> {
    try {
      const response = await this.client.get('/api/auth/validate', {
        validateStatus: () => true,
      });

      if (response.status === 200) {
        return true;
      }

      if (response.status === 404 || response.status === 501) {
        console.warn('Auth validation endpoint unavailable; skipping validation');
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  // User Preferences Management
  async getUserPreferences(): Promise<APIResponse<Record<string, unknown>>> {
    try {
      const response = await this.client.get('/api/user/preferences');
      const raw = response.data;
      return {
        status: response.status,
        data: raw?.data ?? raw,
        error: raw?.error,
        message: raw?.message,
      };
    } catch (error) {
      if (typeof window !== 'undefined') {
        const fallback: Record<string, unknown> = {};
        const assignFallback = (keyName: string, value: unknown) => {
          Object.assign(fallback, { [keyName]: value });
        };
        try {
          const stored = window.localStorage.getItem('tallwave_user_preferences');
          if (stored) {
            const parsed = JSON.parse(stored);
            if (parsed && typeof parsed === 'object') {
              Object.assign(fallback, parsed);
            }
          }
        } catch {
          // ignore corrupted local storage values
        }

        try {
          for (let i = 0; i < window.localStorage.length; i += 1) {
            const key = window.localStorage.key(i);
            if (key && key.startsWith('pref_')) {
              const valueKey = key.slice(5);
              const storedValue = window.localStorage.getItem(key);
              if (storedValue != null) {
                try {
                  assignFallback(valueKey, JSON.parse(storedValue));
                } catch {
                  assignFallback(valueKey, storedValue);
                }
              }
            }
          }
        } catch {
          // ignore iteration issues
        }

        if (Object.keys(fallback).length > 0) {
          return { status: 200, data: fallback };
        }
      }
      return { status: 200, data: {} };
    }
  }

  async updateUserPreferences(preferences: Record<string, unknown>): Promise<APIResponse<Record<string, unknown>>> {
    try {
      const response = await this.client.post('/api/user/preferences', preferences);
      const raw = response.data;
      const payload = raw?.data ?? raw;
      if (typeof window !== 'undefined') {
        try {
          window.localStorage.setItem('tallwave_user_preferences', JSON.stringify(payload ?? {}));
        } catch {
          // ignore storage failures
        }
      }
      return {
        status: response.status,
        data: payload,
        error: raw?.error,
        message: raw?.message,
      };
    } catch (error) {
      // Graceful fallback - use localStorage as backup
      if (typeof window !== 'undefined') {
        try {
          window.localStorage.setItem('tallwave_user_preferences', JSON.stringify(preferences));
        } catch {
          // ignore storage failures
        }
      }
      return { status: 200, data: preferences };
    }
  }

  async setUserPreference(key: string, value: unknown): Promise<APIResponse<unknown>> {
    try {
      const response = await this.client.post('/api/user/preferences', { [key]: value });
      const raw = response.data;
      const payload = raw?.data ?? raw ?? { [key]: value };

      if (typeof window !== 'undefined') {
        try {
          const existingRaw = window.localStorage.getItem('tallwave_user_preferences');
          let existing: Record<string, unknown> = {};
          if (existingRaw) {
            const parsed = JSON.parse(existingRaw);
            if (parsed && typeof parsed === 'object') {
              existing = parsed as Record<string, unknown>;
            }
          }

          const normalizedPayload =
            payload && typeof payload === 'object'
              ? (payload as Record<string, unknown>)
              : { [key]: value };

          const merged = { ...existing, ...normalizedPayload };
          window.localStorage.setItem('tallwave_user_preferences', JSON.stringify(merged));
          window.localStorage.removeItem(`pref_${key}`);
        } catch {
          // ignore localStorage failures
        }
      }

      return {
        status: response.status,
        data: payload,
        error: raw?.error,
        message: raw?.message,
      };
    } catch (error) {
      // Graceful fallback - use localStorage as backup
      if (typeof window !== 'undefined') {
        try {
          window.localStorage.setItem(`pref_${key}`, JSON.stringify(value));
          const existingRaw = window.localStorage.getItem('tallwave_user_preferences');
          let merged: Record<string, unknown> = { [key]: value };
          if (existingRaw) {
            try {
              const parsed = JSON.parse(existingRaw);
              if (parsed && typeof parsed === 'object') {
                merged = { ...(parsed as Record<string, unknown>), [key]: value };
              }
            } catch {
              // ignore parse errors
            }
          }
          window.localStorage.setItem('tallwave_user_preferences', JSON.stringify(merged));
        } catch {
          // ignore storage failures
        }
      }
      return { status: 200, data: { [key]: value } };
    }
  }
}

export const apiService = new APIService();
export default apiService;
