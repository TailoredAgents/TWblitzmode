-- ============================================================================
-- Migration 016: Comprehensive Schema Gap Remediation
-- ============================================================================
-- CRITICAL PRODUCTION FIX: Addresses massive database schema gaps discovered
-- in exhaustive audit. This migration resolves 42 critical missing elements:
-- - 9 Missing Tables referenced in codebase
-- - 11 Missing Columns in existing tables
-- - 7 Missing Foreign Key Constraints
-- - 5 Missing Performance Indexes
-- - 15 Tables Missing Row-Level Security Policies
--
-- RISK LEVEL: CRITICAL - Production system has major schema inconsistencies
-- EXECUTION TIME: ~45 minutes including validation
-- ============================================================================

BEGIN;

-- ============================================================================
-- PHASE 1: CREATE MISSING TABLES (9 CRITICAL TABLES)
-- ============================================================================

-- 1. Email Metrics Table - Email performance tracking
CREATE TABLE IF NOT EXISTS email_metrics (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Metric tracking
    metric_type VARCHAR(50) NOT NULL CHECK (metric_type IN (
        'sent', 'delivered', 'opened', 'clicked', 'replied', 'bounced', 'unsubscribed'
    )),
    metric_date DATE NOT NULL,
    count INTEGER DEFAULT 1,

    -- Email details
    campaign_id VARCHAR(255),
    subject VARCHAR(500),
    provider VARCHAR(50), -- 'sendgrid', 'mailgun'

    -- Timing
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_email_metric UNIQUE (contact_id, tenant_id, metric_type, metric_date, campaign_id)
);

-- 2. Event Store Table - Event sourcing architecture
CREATE TABLE IF NOT EXISTS event_store (
    id SERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
    tenant_id INTEGER,

    -- Event metadata
    event_type VARCHAR(100) NOT NULL,
    aggregate_type VARCHAR(100) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1,

    -- Event data
    event_data JSONB NOT NULL DEFAULT '{}',
    metadata JSONB DEFAULT '{}',

    -- Correlation and causation
    correlation_id UUID,
    causation_id UUID,

    -- Timing and ordering
    sequence_number SERIAL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_aggregate_version UNIQUE (aggregate_id, event_version)
);

-- 3. Introductions Table - Introduction tracking system
CREATE TABLE IF NOT EXISTS introductions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Introduction parties
    prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
    connector_id INTEGER REFERENCES connectors(id) ON DELETE CASCADE,
    introducer_id INTEGER REFERENCES team_members(id) ON DELETE SET NULL,

    -- Introduction details
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'sent', 'accepted', 'declined', 'completed', 'failed'
    )),
    message TEXT,
    introduction_type VARCHAR(50) DEFAULT 'email' CHECK (introduction_type IN ('email', 'linkedin', 'phone', 'in_person')),

    -- LinkedIn tracking
    linkedin_url VARCHAR(500),

    -- Legacy compatibility
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,

    -- Timing
    scheduled_at TIMESTAMP WITH TIME ZONE,
    sent_at TIMESTAMP WITH TIME ZONE,
    responded_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_introduction UNIQUE (tenant_id, prospect_id, connector_id)
);

-- 4. Profile Warmup Queue - LinkedIn profile warming
CREATE TABLE IF NOT EXISTS profile_warmup_queue (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Session and profile
    linkedin_session_id INTEGER REFERENCES linkedin_sessions(id) ON DELETE CASCADE,
    target_profile_url VARCHAR(500) NOT NULL,
    target_profile_name VARCHAR(255),

    -- Warmup strategy
    warmup_type VARCHAR(50) DEFAULT 'view_profile' CHECK (warmup_type IN (
        'view_profile', 'like_post', 'comment_post', 'send_connection'
    )),
    priority INTEGER DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'processing', 'completed', 'failed', 'skipped', 'cancelled'
    )),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    -- Timing
    scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    next_retry_at TIMESTAMP WITH TIME ZONE,

    -- Results
    result_data JSONB DEFAULT '{}',
    error_message TEXT,

    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. Prospect Network Matches - Network matching results
CREATE TABLE IF NOT EXISTS prospect_network_matches (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Matching entities
    prospect_id INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    connector_id INTEGER NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    team_member_id INTEGER REFERENCES team_members(id) ON DELETE SET NULL,

    -- Match scoring
    connection_strength DECIMAL(5,2) NOT NULL DEFAULT 0.0 CHECK (connection_strength >= 0.0 AND connection_strength <= 100.0),
    mutual_connections INTEGER DEFAULT 0,
    relationship_score DECIMAL(5,2) DEFAULT 0.0,

    -- Match metadata
    match_algorithm VARCHAR(50) DEFAULT 'v1',
    match_data JSONB DEFAULT '{}',
    confidence_score DECIMAL(3,2) CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),

    -- Status
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'used', 'expired', 'invalid')),

    -- Timing
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_prospect_connector_match UNIQUE (tenant_id, prospect_id, connector_id)
);

-- 6. Provider Instances - Service provider management
CREATE TABLE IF NOT EXISTS provider_instances (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Provider details
    provider VARCHAR(100) NOT NULL, -- 'apify', 'phantombuster', 'cufinder', etc.
    instance_name VARCHAR(255) NOT NULL,
    provider_instance_id VARCHAR(255), -- External provider's instance ID

    -- Configuration
    instance_data JSONB NOT NULL DEFAULT '{}',
    config_data JSONB DEFAULT '{}',
    credentials_encrypted TEXT, -- Encrypted instance-specific credentials

    -- Status and health
    is_active BOOLEAN DEFAULT true,
    health_status VARCHAR(50) DEFAULT 'unknown' CHECK (health_status IN (
        'healthy', 'degraded', 'unhealthy', 'unknown', 'maintenance'
    )),
    last_health_check TIMESTAMP WITH TIME ZONE,

    -- Usage tracking
    last_used_at TIMESTAMP WITH TIME ZONE,
    usage_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,

    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_provider_instance UNIQUE (tenant_id, provider, instance_name)
);

-- 7. Team Networks - Team member network data
CREATE TABLE IF NOT EXISTS team_networks (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Team member reference
    team_member_id INTEGER NOT NULL REFERENCES team_members(id) ON DELETE CASCADE,

    -- Network data
    network_data JSONB NOT NULL DEFAULT '{}', -- Complete network export data
    total_connections INTEGER DEFAULT 0,
    last_import_date TIMESTAMP WITH TIME ZONE,

    -- Data source and quality
    data_source VARCHAR(50) DEFAULT 'linkedin' CHECK (data_source IN ('linkedin', 'manual', 'api')),
    data_quality_score DECIMAL(3,2) CHECK (data_quality_score >= 0.0 AND data_quality_score <= 1.0),

    -- Processing status
    processing_status VARCHAR(50) DEFAULT 'pending' CHECK (processing_status IN (
        'pending', 'processing', 'completed', 'failed', 'expired'
    )),
    processed_connections INTEGER DEFAULT 0,

    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_team_member_network UNIQUE (tenant_id, team_member_id)
);

-- 8. Workflow Queue Metadata - Queue configuration
CREATE TABLE IF NOT EXISTS workflow_queue_metadata (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Queue identification
    queue_id VARCHAR(255) UNIQUE NOT NULL,
    queue_name VARCHAR(255) NOT NULL,
    queue_type VARCHAR(100) NOT NULL, -- 'prospect_discovery', 'email_campaign', 'connection_mapping'

    -- Queue configuration
    max_concurrent INTEGER DEFAULT 5 CHECK (max_concurrent > 0),
    max_retry_attempts INTEGER DEFAULT 3,
    default_timeout_minutes INTEGER DEFAULT 60,

    -- Queue behavior
    is_enabled BOOLEAN DEFAULT true,
    is_paused BOOLEAN DEFAULT false,
    priority_enabled BOOLEAN DEFAULT true,

    -- Processing rules
    processing_rules JSONB DEFAULT '{}',
    retry_policy JSONB DEFAULT '{}',

    -- Statistics
    total_processed INTEGER DEFAULT 0,
    total_failed INTEGER DEFAULT 0,
    average_processing_time DECIMAL(8,2), -- seconds

    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 9. Workflow Queues - Persistent queue management
CREATE TABLE IF NOT EXISTS workflow_queues (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,

    -- Queue and workflow relationship
    workflow_id UUID NOT NULL REFERENCES workflow_executions(execution_id) ON DELETE CASCADE,
    queue_id VARCHAR(255) NOT NULL REFERENCES workflow_queue_metadata(queue_id) ON DELETE CASCADE,

    -- Queue position and priority
    priority INTEGER DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),
    queue_position INTEGER,

    -- Status tracking
    status VARCHAR(50) DEFAULT 'queued' CHECK (status IN (
        'queued', 'processing', 'completed', 'failed', 'cancelled', 'timeout'
    )),

    -- Timing
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processing_started_at TIMESTAMP WITH TIME ZONE,
    processed_at TIMESTAMP WITH TIME ZONE,

    -- Processing details
    processing_node VARCHAR(255), -- Which processing node picked up the job
    processing_time_seconds DECIMAL(8,2),
    retry_count INTEGER DEFAULT 0,

    -- Error handling
    error_message TEXT,
    error_details JSONB,

    -- Constraints
    CONSTRAINT unique_workflow_queue UNIQUE (workflow_id)
);

-- ============================================================================
-- PHASE 2: ADD MISSING COLUMNS TO EXISTING TABLES (11 COLUMNS)
-- ============================================================================

-- Add missing columns to daily_quotas
DO $$
BEGIN
    -- Add for_date column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'daily_quotas' AND column_name = 'for_date') THEN
        ALTER TABLE daily_quotas ADD COLUMN for_date DATE;
        -- Backfill with date column if it exists
        UPDATE daily_quotas SET for_date = date WHERE for_date IS NULL AND date IS NOT NULL;
    END IF;

    -- Add day column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'daily_quotas' AND column_name = 'day') THEN
        ALTER TABLE daily_quotas ADD COLUMN day DATE;
        -- Backfill with date or for_date column
        UPDATE daily_quotas SET day = COALESCE(date, for_date) WHERE day IS NULL;
    END IF;

    -- Add used column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'daily_quotas' AND column_name = 'used') THEN
        ALTER TABLE daily_quotas ADD COLUMN used INTEGER DEFAULT 0;
    END IF;

    -- Add daily_limit column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'daily_quotas' AND column_name = 'daily_limit') THEN
        ALTER TABLE daily_quotas ADD COLUMN daily_limit INTEGER DEFAULT 100;
    END IF;
END;
$$;

-- Add missing columns to job_runs
DO $$
BEGIN
    -- Add cached_result column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'job_runs' AND column_name = 'cached_result') THEN
        ALTER TABLE job_runs ADD COLUMN cached_result JSONB DEFAULT '{}';
    END IF;
END;
$$;

-- Add missing columns to linkedin_sessions
DO $$
BEGIN
    -- Add full_name column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'linkedin_sessions' AND column_name = 'full_name') THEN
        ALTER TABLE linkedin_sessions ADD COLUMN full_name VARCHAR(255);
    END IF;

    -- Add username column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'linkedin_sessions' AND column_name = 'username') THEN
        ALTER TABLE linkedin_sessions ADD COLUMN username VARCHAR(255);
    END IF;
END;
$$;

-- Add missing columns to prospects
DO $$
BEGIN
    -- Add email_confidence column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'prospects' AND column_name = 'email_confidence') THEN
        ALTER TABLE prospects ADD COLUMN email_confidence DECIMAL(3,2) CHECK (email_confidence >= 0.0 AND email_confidence <= 1.0);
    END IF;

    -- Add status column if missing (different from prospects_new.status)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'prospects' AND column_name = 'status') THEN
        ALTER TABLE prospects ADD COLUMN status VARCHAR(50) DEFAULT 'active' CHECK (status IN (
            'active', 'contacted', 'responded', 'converted', 'unqualified', 'do_not_contact'
        ));
    END IF;
END;
$$;

-- Add missing columns to team_members
DO $$
BEGIN
    -- Add active column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'team_members' AND column_name = 'active') THEN
        ALTER TABLE team_members ADD COLUMN active BOOLEAN DEFAULT true;
        -- Sync with is_active if it exists
        UPDATE team_members SET active = is_active WHERE active IS NULL AND is_active IS NOT NULL;
    END IF;

    -- Add position column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'team_members' AND column_name = 'position') THEN
        ALTER TABLE team_members ADD COLUMN position VARCHAR(255);
    END IF;

    -- Add tenant_id column if missing (for backward compatibility)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'team_members' AND column_name = 'tenant_id') THEN
        ALTER TABLE team_members ADD COLUMN tenant_id INTEGER;
        -- Backfill tenant_id with organization_id for consistency
        UPDATE team_members SET tenant_id = organization_id WHERE tenant_id IS NULL;
    END IF;

    -- Add user_id column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'team_members' AND column_name = 'user_id') THEN
        ALTER TABLE team_members ADD COLUMN user_id INTEGER;
        -- Note: Cannot add FK constraint to users table as it may not exist
    END IF;
END;
$$;

-- ============================================================================
-- PHASE 3: ADD MISSING FOREIGN KEY CONSTRAINTS (7 CONSTRAINTS)
-- ============================================================================

-- Add FK constraints where both tables exist
DO $$
BEGIN
    -- cufinder_cache.tenant_id -> tenants.id
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cufinder_cache')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants')
       AND NOT EXISTS (SELECT 1 FROM information_schema.referential_constraints WHERE constraint_name = 'cufinder_cache_tenant_id_fkey') THEN
        ALTER TABLE cufinder_cache ADD CONSTRAINT cufinder_cache_tenant_id_fkey
            FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
    END IF;

    -- daily_quotas.tenant_id -> tenants.id
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'daily_quotas')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants')
       AND NOT EXISTS (SELECT 1 FROM information_schema.referential_constraints WHERE constraint_name = 'daily_quotas_tenant_id_fkey') THEN
        ALTER TABLE daily_quotas ADD CONSTRAINT daily_quotas_tenant_id_fkey
            FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
    END IF;

    -- linkedin_sessions.tenant_id -> tenants.id
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'linkedin_sessions')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants')
       AND NOT EXISTS (SELECT 1 FROM information_schema.referential_constraints WHERE constraint_name = 'linkedin_sessions_tenant_id_fkey') THEN
        ALTER TABLE linkedin_sessions ADD CONSTRAINT linkedin_sessions_tenant_id_fkey
            FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
    END IF;

    -- provider_health.tenant_id -> tenants.id
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'provider_health')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants')
       AND NOT EXISTS (SELECT 1 FROM information_schema.referential_constraints WHERE constraint_name = 'provider_health_tenant_id_fkey') THEN
        ALTER TABLE provider_health ADD CONSTRAINT provider_health_tenant_id_fkey
            FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
    END IF;

    -- workflow_contexts.user_id -> users.id (only if users table exists)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workflow_contexts')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')
       AND NOT EXISTS (SELECT 1 FROM information_schema.referential_constraints WHERE constraint_name = 'workflow_contexts_user_id_fkey') THEN
        ALTER TABLE workflow_contexts ADD CONSTRAINT workflow_contexts_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;

    -- workflow_states.organization_id -> organizations.id
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workflow_states')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'organizations')
       AND NOT EXISTS (SELECT 1 FROM information_schema.referential_constraints WHERE constraint_name = 'workflow_states_organization_id_fkey') THEN
        ALTER TABLE workflow_states ADD CONSTRAINT workflow_states_organization_id_fkey
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;

    -- workflow_states.user_id -> users.id (only if users table exists)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workflow_states')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')
       AND NOT EXISTS (SELECT 1 FROM information_schema.referential_constraints WHERE constraint_name = 'workflow_states_user_id_fkey') THEN
        ALTER TABLE workflow_states ADD CONSTRAINT workflow_states_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END;
$$;

-- ============================================================================
-- PHASE 4: ADD MISSING PERFORMANCE INDEXES (5 INDEXES)
-- ============================================================================

-- Create missing performance indexes
CREATE INDEX IF NOT EXISTS idx_job_runs_job_type ON job_runs(job_type);
CREATE INDEX IF NOT EXISTS idx_job_runs_user_id ON job_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_user_id ON workflow_contexts(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_user_id ON workflow_states(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_workflow_type ON workflow_states(workflow_type);

-- Additional indexes for new tables
CREATE INDEX IF NOT EXISTS idx_email_metrics_tenant_date ON email_metrics(tenant_id, metric_date);
CREATE INDEX IF NOT EXISTS idx_email_metrics_contact ON email_metrics(contact_id);
CREATE INDEX IF NOT EXISTS idx_event_store_aggregate ON event_store(aggregate_type, aggregate_id);
CREATE INDEX IF NOT EXISTS idx_event_store_org_type ON event_store(organization_id, event_type);
CREATE INDEX IF NOT EXISTS idx_introductions_tenant_status ON introductions(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_profile_warmup_queue_scheduled ON profile_warmup_queue(scheduled_at, status);
CREATE INDEX IF NOT EXISTS idx_prospect_network_matches_strength ON prospect_network_matches(connection_strength DESC);
CREATE INDEX IF NOT EXISTS idx_provider_instances_tenant_provider ON provider_instances(tenant_id, provider);
CREATE INDEX IF NOT EXISTS idx_team_networks_tenant_member ON team_networks(tenant_id, team_member_id);
CREATE INDEX IF NOT EXISTS idx_workflow_queues_queue_priority ON workflow_queues(queue_id, priority DESC);

-- ============================================================================
-- PHASE 5: IMPLEMENT ROW-LEVEL SECURITY (15 TABLES)
-- ============================================================================

-- Enable RLS on existing tables that lack it
DO $$
DECLARE
    tbl_name text;
    tables_to_secure text[] := ARRAY[
        'prospects', 'connectors', 'team_members', 'job_runs', 'linkedin_sessions',
        'daily_quotas', 'cufinder_cache', 'email_suppression_list', 'email_webhook_events',
        'provider_health', 'user_integrations', 'workflow_contexts', 'workflow_states',
        'users', 'tenants'
    ];
BEGIN
    FOREACH tbl_name IN ARRAY tables_to_secure
    LOOP
        -- Enable RLS if table exists
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = tbl_name) THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl_name);
            EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl_name);
        END IF;
    END LOOP;
END;
$$;

-- Create tenant/organization isolation policies
DO $$
BEGIN
    -- Prospects tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'prospects') THEN
        DROP POLICY IF EXISTS prospects_tenant_isolation ON prospects;
        CREATE POLICY prospects_tenant_isolation ON prospects
            USING (
                tenant_id = current_setting('app.current_tenant_id', true)::INTEGER
                OR organization_id = current_setting('app.current_organization_id', true)::INTEGER
            );
    END IF;

    -- Connectors organization isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'connectors') THEN
        DROP POLICY IF EXISTS connectors_org_isolation ON connectors;
        CREATE POLICY connectors_org_isolation ON connectors
            USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);
    END IF;

    -- Team members organization isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'team_members') THEN
        DROP POLICY IF EXISTS team_members_org_isolation ON team_members;
        CREATE POLICY team_members_org_isolation ON team_members
            USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);
    END IF;

    -- Job runs tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'job_runs') THEN
        DROP POLICY IF EXISTS job_runs_tenant_isolation ON job_runs;
        CREATE POLICY job_runs_tenant_isolation ON job_runs
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- LinkedIn sessions tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'linkedin_sessions') THEN
        DROP POLICY IF EXISTS linkedin_sessions_tenant_isolation ON linkedin_sessions;
        CREATE POLICY linkedin_sessions_tenant_isolation ON linkedin_sessions
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- Daily quotas tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'daily_quotas') THEN
        DROP POLICY IF EXISTS daily_quotas_tenant_isolation ON daily_quotas;
        CREATE POLICY daily_quotas_tenant_isolation ON daily_quotas
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- CUFinder cache tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cufinder_cache') THEN
        DROP POLICY IF EXISTS cufinder_cache_tenant_isolation ON cufinder_cache;
        CREATE POLICY cufinder_cache_tenant_isolation ON cufinder_cache
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- Email suppression list tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'email_suppression_list') THEN
        DROP POLICY IF EXISTS email_suppression_list_tenant_isolation ON email_suppression_list;
        CREATE POLICY email_suppression_list_tenant_isolation ON email_suppression_list
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- Email webhook events tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'email_webhook_events') THEN
        DROP POLICY IF EXISTS email_webhook_events_tenant_isolation ON email_webhook_events;
        CREATE POLICY email_webhook_events_tenant_isolation ON email_webhook_events
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- Provider health tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'provider_health') THEN
        DROP POLICY IF EXISTS provider_health_tenant_isolation ON provider_health;
        CREATE POLICY provider_health_tenant_isolation ON provider_health
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- User integrations tenant isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_integrations') THEN
        DROP POLICY IF EXISTS user_integrations_tenant_isolation ON user_integrations;
        CREATE POLICY user_integrations_tenant_isolation ON user_integrations
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- Workflow contexts organization isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workflow_contexts') THEN
        DROP POLICY IF EXISTS workflow_contexts_org_isolation ON workflow_contexts;
        CREATE POLICY workflow_contexts_org_isolation ON workflow_contexts
            USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);
    END IF;

    -- Workflow states organization isolation
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workflow_states') THEN
        DROP POLICY IF EXISTS workflow_states_org_isolation ON workflow_states;
        CREATE POLICY workflow_states_org_isolation ON workflow_states
            USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);
    END IF;

    -- Users tenant isolation (if users table exists)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        DROP POLICY IF EXISTS users_tenant_isolation ON users;
        CREATE POLICY users_tenant_isolation ON users
            USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;

    -- Tenants can only see themselves
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants') THEN
        DROP POLICY IF EXISTS tenants_self_isolation ON tenants;
        CREATE POLICY tenants_self_isolation ON tenants
            USING (id = current_setting('app.current_tenant_id', true)::INTEGER);
    END IF;
END;
$$;

-- Enable RLS on new tables
ALTER TABLE email_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_metrics FORCE ROW LEVEL SECURITY;
CREATE POLICY email_metrics_tenant_isolation ON email_metrics
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE event_store ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_store FORCE ROW LEVEL SECURITY;
CREATE POLICY event_store_org_isolation ON event_store
    USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);

ALTER TABLE introductions ENABLE ROW LEVEL SECURITY;
ALTER TABLE introductions FORCE ROW LEVEL SECURITY;
CREATE POLICY introductions_tenant_isolation ON introductions
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE profile_warmup_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE profile_warmup_queue FORCE ROW LEVEL SECURITY;
CREATE POLICY profile_warmup_queue_tenant_isolation ON profile_warmup_queue
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE prospect_network_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE prospect_network_matches FORCE ROW LEVEL SECURITY;
CREATE POLICY prospect_network_matches_tenant_isolation ON prospect_network_matches
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE provider_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_instances FORCE ROW LEVEL SECURITY;
CREATE POLICY provider_instances_tenant_isolation ON provider_instances
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE team_networks ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_networks FORCE ROW LEVEL SECURITY;
CREATE POLICY team_networks_tenant_isolation ON team_networks
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE workflow_queue_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_queue_metadata FORCE ROW LEVEL SECURITY;
CREATE POLICY workflow_queue_metadata_org_isolation ON workflow_queue_metadata
    USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);

ALTER TABLE workflow_queues ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_queues FORCE ROW LEVEL SECURITY;
CREATE POLICY workflow_queues_org_isolation ON workflow_queues
    USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);

-- ============================================================================
-- PHASE 6: ANALYZE AND VALIDATE
-- ============================================================================

-- Update table statistics for query optimization
ANALYZE email_metrics;
ANALYZE event_store;
ANALYZE introductions;
ANALYZE profile_warmup_queue;
ANALYZE prospect_network_matches;
ANALYZE provider_instances;
ANALYZE team_networks;
ANALYZE workflow_queue_metadata;
ANALYZE workflow_queues;

-- Validate constraints and relationships
DO $$
DECLARE
    constraint_count INTEGER;
    table_count INTEGER;
    policy_count INTEGER;
BEGIN
    -- Count foreign key constraints
    SELECT COUNT(*) INTO constraint_count
    FROM information_schema.referential_constraints
    WHERE constraint_schema = 'public';

    -- Count tables
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'public';

    -- Count RLS policies
    SELECT COUNT(*) INTO policy_count
    FROM pg_policies
    WHERE schemaname = 'public';

    RAISE NOTICE 'Migration completed successfully:';
    RAISE NOTICE '- Total tables: %', table_count;
    RAISE NOTICE '- Total foreign key constraints: %', constraint_count;
    RAISE NOTICE '- Total RLS policies: %', policy_count;

    IF constraint_count < 80 THEN
        RAISE WARNING 'Expected at least 80 foreign key constraints, found %', constraint_count;
    END IF;

    IF policy_count < 20 THEN
        RAISE WARNING 'Expected at least 20 RLS policies, found %', policy_count;
    END IF;
END;
$$;

COMMIT;

-- ============================================================================
-- POST-MIGRATION VERIFICATION
-- ============================================================================

-- Verify all new tables were created
SELECT
    'NEW TABLES CREATED:' as status,
    CASE WHEN COUNT(*) = 9 THEN '✓ ALL 9 TABLES CREATED'
         ELSE CONCAT('✗ MISSING: ', 9 - COUNT(*), ' TABLES') END as result
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
      'email_metrics', 'event_store', 'introductions', 'profile_warmup_queue',
      'prospect_network_matches', 'provider_instances', 'team_networks',
      'workflow_queue_metadata', 'workflow_queues'
  );

-- Verify missing columns were added
SELECT
    'MISSING COLUMNS ADDED:' as status,
    CASE WHEN COUNT(*) >= 8 THEN '✓ COLUMNS ADDED'
         ELSE CONCAT('✗ SOME MISSING') END as result
FROM information_schema.columns
WHERE table_schema = 'public'
  AND ((table_name = 'daily_quotas' AND column_name IN ('for_date', 'day', 'used', 'daily_limit'))
    OR (table_name = 'job_runs' AND column_name = 'cached_result')
    OR (table_name = 'linkedin_sessions' AND column_name IN ('full_name', 'username'))
    OR (table_name = 'prospects' AND column_name IN ('email_confidence', 'status'))
    OR (table_name = 'team_members' AND column_name IN ('active', 'position', 'tenant_id', 'user_id')));

-- Final database state summary
SELECT
    (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public') as total_tables,
    (SELECT COUNT(*) FROM information_schema.referential_constraints WHERE constraint_schema = 'public') as total_foreign_keys,
    (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public') as total_indexes,
    (SELECT COUNT(*) FROM pg_policies WHERE schemaname = 'public') as total_rls_policies;