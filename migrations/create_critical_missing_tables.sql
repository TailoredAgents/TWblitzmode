-- ============================================================================
-- Create Critical Missing Tables
-- ============================================================================
-- Adds the most important missing tables identified in exhaustive scan:
-- 1. tenants (CRITICAL - multi-tenant master table)
-- 2. feature_flags (HIGH - feature flag system)
-- 3. api_usage (HIGH - API monitoring)
-- 4. webhook_records (MEDIUM - webhook tracking)
-- 5. linkedin_campaigns (MEDIUM - LinkedIn campaign management)
-- 6. ai_workflows (MEDIUM - AI workflow configurations)
-- 7. managed_accounts (LOW - account management)
-- ============================================================================

-- ============================================================================
-- 1. TENANTS TABLE (CRITICAL)
-- ============================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,

    -- Tenant metadata
    domain VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'inactive', 'trial')),

    -- Subscription and billing
    subscription_tier VARCHAR(50) DEFAULT 'starter',
    billing_email VARCHAR(255),

    -- Settings
    settings JSONB DEFAULT '{}',
    features JSONB DEFAULT '{}',

    -- Audit fields
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT tenants_slug_format CHECK (slug ~ '^[a-z0-9-]+$')
);

-- Insert the default tenant
INSERT INTO tenants (id, name, slug, status)
VALUES (1, 'Default Tenant', 'default', 'active')
ON CONFLICT (id) DO NOTHING;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tenants_slug ON tenants(slug);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status);

COMMENT ON TABLE tenants IS 'Multi-tenant master table - tenant isolation root';

-- ============================================================================
-- 2. FEATURE FLAGS (Feature Flag System)
-- ============================================================================

CREATE TABLE IF NOT EXISTS feature_flags (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER,

    -- Flag identification
    flag_key VARCHAR(100) UNIQUE NOT NULL,
    flag_name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Flag configuration
    flag_type VARCHAR(50) DEFAULT 'boolean' CHECK (flag_type IN ('boolean', 'string', 'number', 'json')),
    default_value JSONB DEFAULT 'false',

    -- Targeting and rollout
    is_enabled BOOLEAN DEFAULT false,
    rollout_percentage INTEGER DEFAULT 0 CHECK (rollout_percentage >= 0 AND rollout_percentage <= 100),
    target_segments JSONB DEFAULT '[]',

    -- Metadata
    tags JSONB DEFAULT '[]',
    owner_team VARCHAR(100),

    -- Audit fields
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT feature_flags_key_format CHECK (flag_key ~ '^[a-z0-9_-]+$')
);

CREATE INDEX IF NOT EXISTS idx_feature_flags_key ON feature_flags(flag_key);
CREATE INDEX IF NOT EXISTS idx_feature_flags_enabled ON feature_flags(is_enabled);
CREATE INDEX IF NOT EXISTS idx_feature_flags_tenant ON feature_flags(tenant_id);

COMMENT ON TABLE feature_flags IS 'Feature flag system for gradual rollouts';

-- Feature Flag History
CREATE TABLE IF NOT EXISTS feature_flag_history (
    id SERIAL PRIMARY KEY,
    flag_id INTEGER REFERENCES feature_flags(id) ON DELETE CASCADE,

    -- Change tracking
    changed_field VARCHAR(100) NOT NULL,
    old_value JSONB,
    new_value JSONB,

    -- Audit
    changed_by INTEGER,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    change_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_feature_flag_history_flag ON feature_flag_history(flag_id);
CREATE INDEX IF NOT EXISTS idx_feature_flag_history_changed ON feature_flag_history(changed_at DESC);

-- Feature Flag Evaluations
CREATE TABLE IF NOT EXISTS feature_evaluations (
    id BIGSERIAL PRIMARY KEY,
    flag_id INTEGER REFERENCES feature_flags(id) ON DELETE CASCADE,
    tenant_id INTEGER,

    -- Evaluation context
    user_id INTEGER,
    evaluation_context JSONB DEFAULT '{}',

    -- Result
    evaluated_value JSONB NOT NULL,
    was_enabled BOOLEAN NOT NULL,

    -- Audit
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feature_evaluations_flag ON feature_evaluations(flag_id);
CREATE INDEX IF NOT EXISTS idx_feature_evaluations_user ON feature_evaluations(user_id);
CREATE INDEX IF NOT EXISTS idx_feature_evaluations_evaluated ON feature_evaluations(evaluated_at DESC);

COMMENT ON TABLE feature_evaluations IS 'Feature flag evaluation log for analytics';

-- ============================================================================
-- 3. API USAGE (API Monitoring)
-- ============================================================================

CREATE TABLE IF NOT EXISTS api_usage (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Request identification
    request_id VARCHAR(255),
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    api_key_id INTEGER,

    -- Request details
    endpoint VARCHAR(500) NOT NULL,
    http_method VARCHAR(10) NOT NULL,
    request_path VARCHAR(1000),
    query_params JSONB DEFAULT '{}',

    -- Response details
    status_code INTEGER,
    response_time_ms INTEGER,
    response_size_bytes INTEGER,

    -- Rate limiting
    rate_limit_key VARCHAR(255),
    rate_limit_remaining INTEGER,

    -- Error tracking
    error_message TEXT,
    error_code VARCHAR(50),

    -- Metadata
    ip_address VARCHAR(45),
    user_agent TEXT,
    referer VARCHAR(1000),

    -- Audit
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_usage_tenant ON api_usage(tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_usage_org ON api_usage(organization_id);
CREATE INDEX IF NOT EXISTS idx_api_usage_user ON api_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_api_usage_endpoint ON api_usage(endpoint);
CREATE INDEX IF NOT EXISTS idx_api_usage_requested ON api_usage(requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_usage_status ON api_usage(status_code);

COMMENT ON TABLE api_usage IS 'API request tracking for monitoring and billing';

-- ============================================================================
-- 4. WEBHOOK RECORDS (Webhook Tracking)
-- ============================================================================

CREATE TABLE IF NOT EXISTS webhook_records (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Webhook identification
    webhook_url VARCHAR(1000) NOT NULL,
    webhook_type VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,

    -- Payload
    payload JSONB NOT NULL DEFAULT '{}',
    headers JSONB DEFAULT '{}',

    -- Status
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN (
        'pending', 'sending', 'delivered', 'failed', 'retrying', 'cancelled'
    )),

    -- Response tracking
    response_status_code INTEGER,
    response_body TEXT,
    response_time_ms INTEGER,

    -- Retry logic
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    next_retry_at TIMESTAMP,

    -- Error handling
    error_message TEXT,
    error_details JSONB,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_webhook_records_tenant ON webhook_records(tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhook_records_org ON webhook_records(organization_id);
CREATE INDEX IF NOT EXISTS idx_webhook_records_status ON webhook_records(status);
CREATE INDEX IF NOT EXISTS idx_webhook_records_type ON webhook_records(webhook_type);
CREATE INDEX IF NOT EXISTS idx_webhook_records_created ON webhook_records(created_at DESC);

COMMENT ON TABLE webhook_records IS 'Webhook delivery tracking and retry management';

-- Webhook Delivery Attempts
CREATE TABLE IF NOT EXISTS webhook_delivery_attempts (
    id SERIAL PRIMARY KEY,
    webhook_record_id INTEGER NOT NULL REFERENCES webhook_records(id) ON DELETE CASCADE,

    -- Attempt details
    attempt_number INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL,

    -- Response
    response_status_code INTEGER,
    response_body TEXT,
    response_time_ms INTEGER,

    -- Error
    error_message TEXT,

    -- Audit
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_webhook_attempt UNIQUE (webhook_record_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS idx_webhook_delivery_attempts_record ON webhook_delivery_attempts(webhook_record_id);
CREATE INDEX IF NOT EXISTS idx_webhook_delivery_attempts_attempted ON webhook_delivery_attempts(attempted_at DESC);

COMMENT ON TABLE webhook_delivery_attempts IS 'Individual webhook delivery attempt history';

-- ============================================================================
-- 5. LINKEDIN CAMPAIGNS (LinkedIn Campaign Management)
-- ============================================================================

CREATE TABLE IF NOT EXISTS linkedin_campaigns (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Campaign details
    campaign_name VARCHAR(255) NOT NULL,
    campaign_type VARCHAR(50) DEFAULT 'outreach' CHECK (campaign_type IN (
        'outreach', 'nurture', 'engagement', 'content_distribution'
    )),

    -- Configuration
    target_segment JSONB,
    message_sequence JSONB DEFAULT '[]',

    -- Status
    status VARCHAR(50) DEFAULT 'draft' CHECK (status IN (
        'draft', 'active', 'paused', 'completed', 'cancelled'
    )),

    -- Scheduling
    start_date DATE,
    end_date DATE,

    -- Metrics
    total_targets INTEGER DEFAULT 0,
    messages_sent INTEGER DEFAULT 0,
    connections_made INTEGER DEFAULT 0,
    responses_received INTEGER DEFAULT 0,

    -- Audit
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_linkedin_campaigns_tenant ON linkedin_campaigns(tenant_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_campaigns_org ON linkedin_campaigns(organization_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_campaigns_status ON linkedin_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_linkedin_campaigns_created ON linkedin_campaigns(created_at DESC);

COMMENT ON TABLE linkedin_campaigns IS 'LinkedIn campaign orchestration';

-- LinkedIn Campaign Messages
CREATE TABLE IF NOT EXISTS linkedin_campaign_messages (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES linkedin_campaigns(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,

    -- Message details
    sequence_number INTEGER NOT NULL,
    message_template TEXT NOT NULL,
    delay_days INTEGER DEFAULT 0,

    -- Targeting
    send_conditions JSONB DEFAULT '{}',

    -- Metrics
    sent_count INTEGER DEFAULT 0,
    response_count INTEGER DEFAULT 0,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_campaign_sequence UNIQUE (campaign_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_campaign_messages_campaign ON linkedin_campaign_messages(campaign_id);

COMMENT ON TABLE linkedin_campaign_messages IS 'LinkedIn campaign message sequences';

-- LinkedIn Metrics
CREATE TABLE IF NOT EXISTS linkedin_metrics (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,

    -- Metric identification
    metric_date DATE NOT NULL,
    metric_type VARCHAR(100) NOT NULL,

    -- Metric values
    metric_value DECIMAL(15,4) NOT NULL,
    metric_count INTEGER DEFAULT 0,

    -- Dimensions
    dimensions JSONB DEFAULT '{}',

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_linkedin_metric UNIQUE (tenant_id, organization_id, metric_date, metric_type, dimensions)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_metrics_tenant ON linkedin_metrics(tenant_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_metrics_org ON linkedin_metrics(organization_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_metrics_date ON linkedin_metrics(metric_date DESC);
CREATE INDEX IF NOT EXISTS idx_linkedin_metrics_type ON linkedin_metrics(metric_type);

COMMENT ON TABLE linkedin_metrics IS 'LinkedIn activity and performance metrics';

-- LinkedIn Daily Usage
CREATE TABLE IF NOT EXISTS linkedin_daily_usage (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    linkedin_session_id INTEGER REFERENCES linkedin_sessions(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,

    -- Usage date
    usage_date DATE NOT NULL,

    -- Usage counters
    profile_views INTEGER DEFAULT 0,
    connection_requests_sent INTEGER DEFAULT 0,
    messages_sent INTEGER DEFAULT 0,
    inmails_sent INTEGER DEFAULT 0,
    posts_created INTEGER DEFAULT 0,
    posts_liked INTEGER DEFAULT 0,
    posts_commented INTEGER DEFAULT 0,

    -- Limits
    daily_limit_reached BOOLEAN DEFAULT false,
    limit_reset_at TIMESTAMP,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_linkedin_daily_usage UNIQUE (tenant_id, linkedin_session_id, usage_date)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_daily_usage_tenant ON linkedin_daily_usage(tenant_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_daily_usage_session ON linkedin_daily_usage(linkedin_session_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_daily_usage_date ON linkedin_daily_usage(usage_date DESC);

COMMENT ON TABLE linkedin_daily_usage IS 'Daily LinkedIn usage tracking for rate limiting';

-- ============================================================================
-- 6. AI WORKFLOWS (AI Workflow Configurations)
-- ============================================================================

CREATE TABLE IF NOT EXISTS ai_workflows (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Workflow identification
    workflow_name VARCHAR(255) NOT NULL,
    workflow_type VARCHAR(100) NOT NULL,
    description TEXT,

    -- Configuration
    workflow_config JSONB NOT NULL DEFAULT '{}',
    ai_model VARCHAR(100) DEFAULT 'gpt-4',
    temperature DECIMAL(3,2) DEFAULT 0.7,

    -- Prompt configuration
    system_prompt TEXT,
    user_prompt_template TEXT,

    -- Status
    is_active BOOLEAN DEFAULT true,
    version VARCHAR(20) DEFAULT '1.0.0',

    -- Audit
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_ai_workflow_name UNIQUE (tenant_id, organization_id, workflow_name)
);

CREATE INDEX IF NOT EXISTS idx_ai_workflows_tenant ON ai_workflows(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ai_workflows_org ON ai_workflows(organization_id);
CREATE INDEX IF NOT EXISTS idx_ai_workflows_type ON ai_workflows(workflow_type);
CREATE INDEX IF NOT EXISTS idx_ai_workflows_active ON ai_workflows(is_active);

COMMENT ON TABLE ai_workflows IS 'AI workflow configurations and prompt templates';

-- AI Assistants
CREATE TABLE IF NOT EXISTS ai_assistants (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Assistant identification
    assistant_name VARCHAR(255) NOT NULL,
    assistant_type VARCHAR(100) NOT NULL,
    description TEXT,

    -- Configuration
    ai_model VARCHAR(100) DEFAULT 'gpt-4',
    system_prompt TEXT NOT NULL,
    tools JSONB DEFAULT '[]',

    -- Capabilities
    can_execute_actions BOOLEAN DEFAULT false,
    requires_approval BOOLEAN DEFAULT true,

    -- Status
    is_active BOOLEAN DEFAULT true,

    -- Audit
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_ai_assistant_name UNIQUE (tenant_id, organization_id, assistant_name)
);

CREATE INDEX IF NOT EXISTS idx_ai_assistants_tenant ON ai_assistants(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ai_assistants_org ON ai_assistants(organization_id);
CREATE INDEX IF NOT EXISTS idx_ai_assistants_type ON ai_assistants(assistant_type);
CREATE INDEX IF NOT EXISTS idx_ai_assistants_active ON ai_assistants(is_active);

COMMENT ON TABLE ai_assistants IS 'AI assistant definitions and configurations';

-- ============================================================================
-- 7. MANAGED ACCOUNTS (Account Management)
-- ============================================================================

CREATE TABLE IF NOT EXISTS managed_accounts (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Account details
    account_name VARCHAR(255) NOT NULL,
    account_type VARCHAR(50) NOT NULL CHECK (account_type IN (
        'linkedin', 'email', 'twitter', 'facebook', 'instagram', 'other'
    )),
    account_identifier VARCHAR(255) NOT NULL,

    -- Credentials (encrypted)
    credentials_encrypted TEXT,
    encryption_key_id VARCHAR(255),

    -- Status
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN (
        'active', 'paused', 'suspended', 'expired', 'invalid'
    )),

    -- Health monitoring
    last_used_at TIMESTAMP,
    last_health_check_at TIMESTAMP,
    health_status VARCHAR(50) DEFAULT 'unknown',

    -- Limits
    daily_limit INTEGER,
    monthly_limit INTEGER,

    -- Metadata
    metadata JSONB DEFAULT '{}',

    -- Audit
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_managed_account UNIQUE (tenant_id, account_type, account_identifier)
);

CREATE INDEX IF NOT EXISTS idx_managed_accounts_tenant ON managed_accounts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_managed_accounts_org ON managed_accounts(organization_id);
CREATE INDEX IF NOT EXISTS idx_managed_accounts_type ON managed_accounts(account_type);
CREATE INDEX IF NOT EXISTS idx_managed_accounts_status ON managed_accounts(status);

COMMENT ON TABLE managed_accounts IS 'Managed third-party account credentials and monitoring';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify all tables were created
SELECT
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants') THEN '✓' ELSE '✗' END as tenants,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'feature_flags') THEN '✓' ELSE '✗' END as feature_flags,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'api_usage') THEN '✓' ELSE '✗' END as api_usage,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'webhook_records') THEN '✓' ELSE '✗' END as webhook_records,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'linkedin_campaigns') THEN '✓' ELSE '✗' END as linkedin_campaigns,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ai_workflows') THEN '✓' ELSE '✗' END as ai_workflows,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'managed_accounts') THEN '✓' ELSE '✗' END as managed_accounts;
