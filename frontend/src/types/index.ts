// TypeScript types for Tallwave dashboard
// September 2025 AI Integration with Human-in-the-Loop Approval

export interface User {
  id: number | string;
  email: string;
  name: string;
  role: 'admin' | 'user';
  organization?: Organization | null;
  tenant_id?: number | string;
  accepted_terms_at?: string | null;
  cookie_status?: string;
  organization_slug?: string | null;
}

export interface Organization {
  id: number | string;
  name: string;
  domain?: string;
  industry?: string;
  size?: string;
  status: 'active' | 'inactive' | 'suspended';
  subscription_tier: 'starter' | 'professional' | 'enterprise';
  slug?: string | null;
}

export interface Prospect {
  id: number;
  organization_id: number | string;
  company: string;
  full_name: string;
  role?: string;
  email?: string;
  linkedin_url?: string;
  location?: string;
  headline?: string;
  status: 'pending_lookup' | 'lookup_complete' | 'mutuals_found' | 'enriched' | 'scheduled' | 'contacted';
  priority: 'low' | 'medium' | 'high' | 'urgent';
  created_at: string;
  updated_at: string;
  top_connectors?: Connector[];
}

export interface Connector {
  id: number;
  full_name: string;
  linkedin_url?: string;
  headline?: string;
  company?: string;
  email?: string;
  ranking_score: number;
  rank: number;
  team_member_id?: number;
  email_status: 'pending' | 'available' | 'unavailable' | 'bounced';
}

export interface TeamMember {
  id: number;
  name: string;
  email: string | null;
  role: 'admin' | 'user';
  status: string;
  created_at: string;
  cookie_status: 'pending' | 'valid' | 'invalid' | 'expired' | 'missing';
  last_validated_at?: string | null;
  last_login_at?: string | null;
  accepted_terms_at?: string | null;
}

export interface EmailTemplate {
  id: string;
  name: string;
  subject: string;
  body: string;
  variables: string[];
  category: 'introduction' | 'follow-up' | 'proposal' | 'meeting';
  created_at: string;
  updated_at: string;
}

export interface EmailCampaign {
  id: string;
  name: string;
  template_id: string;
  status: 'draft' | 'scheduled' | 'active' | 'completed' | 'paused';
  recipients_count: number;
  sent_count: number;
  open_rate: number;
  click_rate: number;
  scheduled_at?: string;
  created_at: string;
}

export interface EmailMetrics {
  total_sent: number;
  total_delivered: number;
  total_opened: number;
  total_clicked: number;
  bounce_rate: number;
  unsubscribe_rate: number;
}

export interface CookieVaultUserSummary {
  userId: string;
  active: number;
  expired: number;
  expiringSoon: number;
  stale: number;
  latestLabel?: string;
  latestCreatedAt?: string;
  latestExpiresAt?: string;
  rotationDueAt?: string;
  rotationRecommended: boolean;
  vaultItemIds: string[];
}

export interface CookieVaultSummary {
  tenantId: string;
  totalItems: number;
  activeItems: number;
  expiredItems: number;
  expiringSoon: number;
  staleItems: number;
  rotationRecommended: boolean;
  status: 'healthy' | 'warning' | 'missing';
  message: string;
  lastRotationAt?: string | null;
  missingVaultEntries: number;
  missingVaultUsers: string[];
  userSummaries: CookieVaultUserSummary[];
  generatedAt: string;
}

// September 2025 AI Workflow Types
export interface AIWorkflow {
  workflow_id: string;
  type: 'prospect_analysis' | 'email_generation' | 'network_mapping';
  status: 'initiated' | 'pending_approval' | 'approved' | 'rejected' | 'completed' | 'failed';
  organization_id: string;
  user_id: string;
  input_data: Record<string, unknown> & {
    name?: string;
    template_id?: string | number;
  };
  result?: Record<string, unknown>;
  pending_approvals: string[];
  created_at: string;
  updated_at: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: 'prospecting' | 'outreach' | 'qualification' | 'research' | 'follow_up';
  icon?: React.ComponentType<unknown>;
  status?: 'available' | 'running' | 'paused';
  autonomous?: boolean;
  estimatedTime?: string;
  requirements?: string[];
  configuration?: Record<string, unknown>;
  metrics?: {
    executions?: number;
    success_rate?: number;
    avg_time?: string;
    results_generated?: number;
  };
}

// Human-in-the-Loop Approval Types
export interface ApprovalRequest {
  approval_id: string;
  workflow_id: string;
  action: string;
  description: string;
  status: 'pending' | 'approved' | 'rejected' | 'escalated' | 'timeout';
  priority: 'low' | 'medium' | 'high' | 'critical';
  context: Record<string, unknown>;
  risk_score?: number;
  requested_at: string;
  timeout_at: string;
  approver_id?: string;
  approval_comments?: string;
  rejection_reason?: string;
  tenant_id?: number;
}

export interface IntegrationSet {
  id: number;
  organization_id: number;
  apify_token?: string;
  apify_actor_id?: string;
  cufinder_api_key?: string;
  email_provider_config?: Record<string, unknown>;
  feature_flags: Record<string, unknown>;
  quota_config: QuotaConfig;
  created_at: string;
  updated_at: string;
}

export interface QuotaConfig {
  email_quota: number;
  weekly_limit: number;
  daily_limit: number;
  scheduling_window: {
    start_hour: number;
    end_hour: number;
    timezone: string;
  };
}

export interface AnalyticsOverview {
  prospects: {
    total: number;
    by_status: Record<string, number>;
    this_week: number;
    completion_rate: number;
    with_connectors?: number;
    activity_trend?: Array<{ name: string; contacts: number; responses: number; meetings?: number }>;
    response_trend?: Array<{ month: string; rate: number }>;
  };
  connectors: {
    total: number;
    with_emails: number;
    avg_score: number;
  };
  workflows: {
    total: number;
    pending_approval: number;
    completed_this_week: number;
    success_rate: number;
    distribution?: Array<{ name: string; value: number }>;
  };
  quotas: {
    emails_sent_this_week: number;
    weekly_limit: number;
    utilization: number;
  };
  integrations: {
    apify: 'connected' | 'disconnected' | 'error';
    cufinder: 'connected' | 'disconnected' | 'error';
    email_provider: 'connected' | 'disconnected' | 'error';
  };
  metadata?: {
    last_updated?: string;
    requested_days?: number;
    tenant_id?: string;
    user_id?: number;
  };
}

export interface IntegrationHealthStatus {
  integration_type: string;
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  last_success: string | null;
  last_failure: string | null;
  success_rate: number;
  avg_response_time_ms: number;
  error_count_24h: number;
  total_calls_24h: number;
  configuration_valid: boolean;
  last_check: string;
}

export interface ProviderHealthStatus {
  provider: string;
  configured: boolean;
  source: 'tenant' | 'environment' | 'missing';
  message: string;
  cookiesConfigured?: boolean;
  pendingRequests?: number;
  pendingRuns?: number;
  lastRequest?: {
    requested_at: string;
    full_name?: string | null;
    company?: string | null;
    domain?: string | null;
    note?: string | null;
  } | null;
  lastRun?: {
    requested_at: string;
    profile_url?: string | null;
    note?: string | null;
    tenant_id?: number | null;
  } | null;
  mode?: string;
  reason?: string;
  disabledReason?: string | null;
  kmsEnabled?: boolean;
  keySource?: string | null;
  keyConfigured?: boolean;
  apiConfigured?: boolean;
  // Stripe-specific fields
  webhookConfigured?: boolean;
  accountId?: string;
  businessProfile?: string;
  // Email service-specific fields
  fromEmailConfigured?: boolean;
  fromEmail?: string | null;
  // Error handling
  error?: string;
}

export interface CorporateWorkflowRun {
  workflow_id: string;
  status: string;
  organization_id?: string;
  tenant_id?: string;
  user_id?: number | string;
  stage?: string | null;
  type?: string;
  prospects_processed?: number;
  connectors_found?: number;
  emails_scheduled?: number;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
  error_message?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CorporateWorkflowMetrics {
  period_days: number;
  total_workflows: number;
  completed_workflows: number;
  failed_workflows: number;
  active_workflows: number;
  running_workflows?: number;
  workflows_running?: number;
  average_approval_time_minutes?: number;
  completion_rate_percent: number;
  failure_rate_percent: number;
  total_prospects_processed: number;
  total_connectors_found: number;
  total_emails_scheduled: number;
  average_prospects_per_workflow: number;
  average_connectors_per_workflow: number;
}

// WebSocket Types for Real-time Updates
export type WebSocketEventType =
  | 'approval_request'
  | 'approval_decision'
  | 'approval_timeout'
  | 'workflow_update'
  | 'cookie_update'
  | 'workflow_progress'
  | 'prospect_update'
  | 'system_notification'
  | 'metrics_update'
  | 'job_status'
  | 'agent_response'
  | 'typing'
  | 'error'
  | 'connection_ack'
  | 'pong'
  | 'message';

export interface WebSocketMessage {
  type?: WebSocketEventType;
  event?: WebSocketEventType;
  data?: unknown;
  approval?: unknown;
  workflow?: unknown;
  notification?: unknown;
  payload?: unknown;
  timestamp?: string;
  [key: string]: unknown;
}

// API Response Types
export interface APIResponse<T> {
  data?: T;
  error?: string;
  message?: string;
  status: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  pagination: {
    page: number;
    limit: number;
    total: number;
    pages: number;
  };
}

// Form Types
export interface LoginForm {
  userId?: number;
  email?: string;
  password: string;
}

export interface LoginRosterUser {
  id: number;
  displayName: string;
  firstName?: string | null;
  lastName?: string | null;
  lastLoginAt?: string | null;
}

export interface MasterAddTeamMemberPayload {
  master_password: string;
  name: string;
  email: string;
  li_at?: string;
  jsessionid?: string;
  cookie_label?: string;
  user_agent?: string;
}

export interface RegistrationRequest {
  registrationKey: string;
  email: string;
  firstName: string;
  lastName: string;
  password: string;
  organizationSlug: string;
}

export interface OnboardingChecklist {
  accept_terms: boolean;
  cookie_required: boolean;
}

export interface OnboardingStalledMember {
  id: number;
  name: string;
  email?: string | null;
  role: string;
  reasons: string[];
}

export interface OnboardingProgress {
  total_members: number;
  accepted_terms: number;
  pending_terms: number;
  cookie_valid: number;
  cookie_pending: number;
  never_logged_in: number;
  // Seat invites retired; kept optional for backward compatibility
  invited_members?: number;
  stalled_members: OnboardingStalledMember[];
  generated_at: string;
  auto_nudge?: {
    enabled: boolean;
    cooldown_seconds: number;
    last_sent_at?: string | null;
    last_notified?: string[];
    errors?: string[];
  };
}

export interface OnboardingNudgeResponse {
  notified: number;
  stalled_members: OnboardingStalledMember[];
  message: string;
}

export interface RedeemRegistrationResponse {
  token: string;
  user_id: number;
  team_member_id: number;
  organization_id: number;
  tenant_id: string;
  onboarding: OnboardingChecklist;
}

export interface CompanyRegistrationPayload {
  companyName: string;
  domain: string;
  slug: string;
  companyIndustry?: string;
  plan: {
    tier: string;
    priceId: string;
    seats: number;
  };
  seatCount: number;
  billing: {
    paymentMethodId: string;
    email: string;
    taxId?: string;
    address: {
      line1: string;
      city: string;
      state?: string;
      postalCode: string;
      country: string;
    };
    notes?: string;
  };
  admin: {
    email: string;
    firstName: string;
    lastName: string;
    password: string;
    jobTitle?: string;
  };
}

export interface CompanyRegistrationDevPayload {
  companyName: string;
  domain?: string;
  slug?: string;
  planTier?: string;
  seatCount?: number;
  notes?: string;
  admin: {
    email: string;
    firstName: string;
    lastName: string;
    password: string;
    jobTitle?: string;
  };
}

export interface SeatPolicy {
  type: string;
  description?: string;
  maxSeats?: number | null;
}

export interface CompanyRegistrationResponse {
  organization: {
    id: number;
    tenant_id: number;
    name: string;
    slug: string;
    domain: string | null;
    subscription_tier: string;
    max_team_members: number;
    stripe_customer_id?: string | null;
    stripe_subscription_id?: string | null;
    stripe_price_id?: string | null;
    stripe_product_id?: string | null;
    billing_status?: string | null;
  };
  admin: {
    id: number;
    team_member_id: number;
    email: string;
    first_name: string;
    last_name: string;
  };
  token: string;
  registration_keys: Array<{
    id: number;
    key: string;
    masked_key: string;
    status: string;
    expires_at?: string;
  }>;
  stripe_customer_id?: string;
  stripe_subscription_id?: string;
  billing_status?: string | null;
}

export interface SeatSummary {
  active: number;
  limit: number;
  unused_keys: number;
}

export interface SeatRequestRecord {
  requested_at: string;
  additional_seats: number;
  new_limit: number;
  notes?: string | null;
  requester_email?: string | null;
  requested_by?: string | null;
  seats?: number | null;
}

export interface CredentialStatus {
  configured: boolean;
  masked?: string | null;
}

export interface AccountOverview {
  account_status: string;
  subscription_status?: string | null;
  account_health?: string | null;
  trial_ends_at?: string | null;
  current_period_end?: string | null;
  seat_limit: number;
  seat_used: number;
  seat_policy: SeatPolicy;
  seat_requests: SeatRequestRecord[];
  notes?: string | null;
  referral_source?: string | null;
  auto_nudge?: unknown;
  created_at?: string | null;
  created_from_ip?: string | null;
}

export interface TierDetails {
  userTier: 'tier1' | 'tier2' | 'tier3';
  organizationTier: 'tier1' | 'tier2' | 'tier3';
  userCapabilities: string[];
  organizationCapabilities: string[];
  features: string[];
  limits: Record<string, unknown>;
  automationEnabled: boolean;
  cookieVaultAccess: boolean;
  httpFallbackEnabled: boolean;
  safeTopicGuidance: string[];
  guardrails: Record<string, string>;
  organization?: {
    id?: number | null;
    name?: string | null;
    slug?: string | null;
    subscriptionTier?: string | null;
    maxTeamMembers?: number | null;
  } | null;
}

export type FeatureFlagMap = Record<string, boolean>;

export interface RegistrationOptions {
  industries: string[];
  company_sizes: string[];
  developer_mode: boolean;
  seat_policy: SeatPolicy;
}

export interface OrganizationProfile {
  id: number;
  tenant_id: number;
  name: string;
  slug: string;
  domain?: string | null;
  subscription_tier: string;
  max_team_members: number;
  status: string;
  billing_details?: Record<string, unknown> | null;
  account_settings?: Record<string, unknown> | null;
  seat_summary: SeatSummary;
  account_overview?: AccountOverview | null;
  tier_details?: TierDetails | null;
  feature_flags?: FeatureFlagMap | null;
}

export interface OrganizationSearchResult {
  id: number;
  name: string;
  slug: string;
  domain?: string | null;
}

export interface RegistrationKeyListItem {
  id: number;
  masked_key: string;
  status: string;
  key?: string;
  assigned_to?: string | null;
  assigned_email?: string | null;
  assigned_team_member_id?: number | null;
  created_at_human?: string | null;
  expires_at_human?: string | null;
  created_at?: string | null;
  used_at?: string | null;
  released_at?: string | null;
  expires_at?: string | null;
}

export interface RegistrationKeyResponse {
  id: number;
  key: string;
  masked_key: string;
  status: string;
  expires_at?: string | null;
  download_url?: string | null;
}

export interface RegistrationKeyDownloadPayload {
  key: string;
  registration_key_id: number;
  organization_id: number;
  expires_at?: string | null;
}

export interface CookieStatus {
  id?: number;
  status: 'pending' | 'valid' | 'invalid' | 'expired' | 'missing';
  status_detail?: string | null;
  last_validated_at?: string | null;
  updated_at?: string | null;
  expires_at?: string | null;
  last_used_at?: string | null;
  usage_count?: number;
  error_count?: number;
  last_error?: string | null;
  last_error_at?: string | null;
  user_id?: number | null;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  role?: string | null;
  vault_item_id?: string | null;
  locked_at?: string | null;
  lock_expires_at?: string | null;
  locked_by?: string | null;
}

export interface CookieOverview {
  total: number;
  valid: number;
  pending: number;
  invalid: number;
  expired: number;
  expiring_soon: number;
  last_event_at?: string | null;
  scraping_paused: boolean;
  scraping_paused_reason?: string | null;
  scraping_paused_at?: string | null;
}

export interface CookieEvent {
  event_type: string;
  status: string;
  message?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ScrapingPolicyUpdatePayload {
  paused: boolean;
  reason?: string | null;
}

export interface ProspectImportForm {
  csv_data: string;
  import_name: string;
}

export interface AIWorkflowForm {
  workflow_type: string;
  input_data: Record<string, unknown>;
  priority: string;
}

export interface ApprovalDecisionForm {
  decision: 'approve' | 'reject';
  notes?: string;
}

// Enhanced UI Component Types for Glassmorphic Design
export interface ProspectCardProps {
  prospect: Prospect;
  onConnectorSelect?: (connector: Connector) => void;
  onProspectAction?: (action: string, prospect: Prospect) => void;
  className?: string;
}

export interface ConnectorBadgeProps {
  connector: Connector;
  rank: number;
  onClick?: () => void;
  size?: 'sm' | 'md' | 'lg';
  variant?: 'default' | 'gradient' | 'glass';
}

export interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'strong' | 'interactive';
  hover?: boolean;
  blur?: 'sm' | 'md' | 'lg' | 'xl';
}

export interface ProspectsGridProps {
  prospects: Prospect[];
  loading?: boolean;
  onProspectSelect?: (prospect: Prospect) => void;
  onConnectorSelect?: (connector: Connector, prospect: Prospect) => void;
  filters?: ProspectFilters;
  onFiltersChange?: (filters: ProspectFilters) => void;
}

export interface ProspectFilters {
  status?: string[];
  priority?: string[];
  company?: string;
  search?: string;
  hasConnectors?: boolean;
  dateRange?: {
    start: string;
    end: string;
  };
}

export interface MessageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connector: Connector;
  prospect: Prospect;
  onSend?: (message: string) => void;
}

// Enhanced Connector interface with UI-specific properties
export interface ConnectorWithContext extends Connector {
  connection_degree?: number;
  relationship_strength?: number;
  mutual_context?: string;
  shared_experiences?: string[];
  reason_codes?: string[];
  profile_picture_url?: string;
  location?: string;
  is_team_member?: boolean;
}

// Enhanced Prospect interface with UI-specific properties
export interface ProspectWithConnectors extends Prospect {
  connectors_count?: number;
  top_connectors?: ConnectorWithContext[];
  company_size?: string;
  industry?: string;
  about?: string;
  tags?: string[];
  notes?: string;
  profile_picture_url?: string;
  last_contact_date?: string;
  response_rate?: number;
}

// Analytics and Dashboard Types
export interface DashboardMetrics {
  prospects: {
    total: number;
    new_this_week: number;
    completion_rate: number;
    by_status: Record<string, number>;
    by_priority: Record<string, number>;
  };
  connectors: {
    total: number;
    avg_per_prospect: number;
    email_coverage: number;
    team_members_coverage: number;
  };
  engagement: {
    emails_sent: number;
    response_rate: number;
    meetings_scheduled: number;
    conversion_rate: number;
  };
  performance: {
    processing_time_avg: number;
    success_rate: number;
    cost_per_prospect: number;
    roi_estimate: number;
  };
}

// Theme and UI State Types
export interface ThemeConfig {
  mode: 'light' | 'dark' | 'system';
  glassIntensity: number;
  animations: boolean;
  reducedMotion: boolean;
  colorScheme: 'blue' | 'purple' | 'green' | 'custom';
}

export interface UIState {
  sidebarCollapsed: boolean;
  activeView: string;
  notifications: Notification[];
  loading: Record<string, boolean>;
  errors: Record<string, string>;
}

export interface Notification {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
  actions?: NotificationAction[];
}

export interface NotificationAction {
  label: string;
  action: string;
  variant?: 'primary' | 'secondary' | 'destructive';
}

// Communication Hub Types
export interface Message {
  id: string;
  conversation_id: string;
  sender_type: 'human' | 'ai';
  sender_name?: string;
  content: string;
  message_type: 'text' | 'approval_request';
  status: 'sent' | 'pending' | 'failed';
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface Conversation {
  id: string;
  title: string;
  participants: Array<{
    id: string;
    name: string;
    type: 'human' | 'ai';
  }>;
  status: 'active' | 'paused' | 'archived' | 'pending_approval';
  priority: 'low' | 'medium' | 'high';
  organization_id: number;
  created_at: string;
  updated_at: string;
  messages?: Message[];
  unread_count: number;
}

export interface Agent {
  id: string;
  name: string;
  type: string;
  status: 'active' | 'paused' | 'error' | 'idle' | 'configuring';
  description?: string;
  capabilities?: string[];
  configuration?: Record<string, unknown>;
  metrics?: {
    tasks_completed: number;
    uptime: string;
    success_rate: number;
  };
  last_activity: string;
  error_message?: string;
  organization_id: number;
}

export interface CommunicationHubFilters extends Record<string, unknown> {
  status?: 'active' | 'paused' | 'archived' | 'pending_approval';
  priority?: 'low' | 'medium' | 'high';
  participant_type?: 'human' | 'ai';
  organization_id?: string;
  date_range?: {
    start: string;
    end: string;
  };
}

// Agent Events Types for Communication Hub Enhancement - September 2025
export type AgentEventLevel = 'debug' | 'info' | 'warning' | 'error' | 'critical';

export type AgentEventType =
  | 'agent_start'
  | 'agent_stop'
  | 'agent_error'
  | 'task_start'
  | 'task_complete'
  | 'task_error'
  | 'api_call'
  | 'api_response'
  | 'workflow_start'
  | 'workflow_complete'
  | 'user_interaction'
  | 'approval_request'
  | 'approval_decision'
  | 'communication'
  | 'system_event';

export interface AgentEvent {
  id: number;
  event_id: string;
  session_id?: string;
  event_type: AgentEventType;
  agent_id: string;
  level: AgentEventLevel;
  message: string;
  suggestion?: string; // Actionable suggestion for users
  tenant_id?: string;
  user_id?: string;
  workflow_id?: string;
  task_id?: string;
  metadata: Record<string, unknown>;
  organization_id?: number;
  created_at: string;
  updated_at: string;
}

export interface AgentEventCreate {
  event_type: AgentEventType;
  agent_id: string;
  level?: AgentEventLevel;
  message: string;
  suggestion?: string;
  tenant_id?: string;
  user_id?: string;
  workflow_id?: string;
  task_id?: string;
  metadata?: Record<string, unknown>;
  organization_id?: number;
}

export interface AgentEventFilters {
  agent_id?: string;
  event_type?: AgentEventType;
  level?: AgentEventLevel;
  organization_id?: string;
  limit?: number;
  offset?: number;
}

export interface AgentEventsSummary {
  level_counts: Record<AgentEventLevel, number>;
  top_event_types: Array<{
    event_type: AgentEventType;
    count: number;
  }>;
  active_agents: Array<{
    agent_id: string;
    event_count: number;
    last_activity: string;
  }>;
  connected_clients?: number;
  organizations_connected?: number;
}

export interface AgentEventsResponse {
  success: boolean;
  data: AgentEvent[];
  pagination?: {
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  };
  message?: string;
}

export interface AgentEventResponse {
  success: boolean;
  data: AgentEvent;
  message?: string;
}

export interface AgentEventsSummaryResponse {
  success: boolean;
  data: AgentEventsSummary;
  message?: string;
}

// WebSocket message types for agent events
export interface AgentEventWebSocketMessage {
  type: 'agent_event' | 'connection_established' | 'pong' | 'error';
  data: AgentEvent | { message: string; connection_id?: string };
  timestamp: string;
}

// UI Component Props for Agent Events
export interface AgentEventCardProps {
  event: AgentEvent;
  onSuggestionClick?: (suggestion: string) => void;
  className?: string;
  showSuggestion?: boolean;
  compact?: boolean;
}

export interface AgentEventsFeedProps {
  events: AgentEvent[];
  loading?: boolean;
  onEventSelect?: (event: AgentEvent) => void;
  onSuggestionClick?: (suggestion: string, event: AgentEvent) => void;
  filters?: AgentEventFilters;
  onFiltersChange?: (filters: AgentEventFilters) => void;
  realTimeEnabled?: boolean;
  className?: string;
}

export interface SuggestionCalloutProps {
  suggestion: string;
  event: AgentEvent;
  onDismiss?: () => void;
  onAction?: (action: string) => void;
  variant?: 'info' | 'warning' | 'error' | 'success';
  className?: string;
}

export interface AgentEventBadgeProps {
  level: AgentEventLevel;
  count?: number;
  size?: 'sm' | 'md' | 'lg';
  variant?: 'default' | 'outline' | 'solid';
  showPulse?: boolean;
}
