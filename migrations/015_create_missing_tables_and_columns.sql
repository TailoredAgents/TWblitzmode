-- ============================================================================
-- Migration 015: Create Missing Tables and Columns
-- ============================================================================
-- Addresses critical database schema gaps identified in comprehensive audit:
-- - Missing workflow orchestration tables (templates, executions, node_executions)
-- - Missing interactions table for contact relationship scoring
-- - Missing analytics and logging tables (daily_metrics, email_logs)
-- - Missing tenant_id columns for multi-tenant isolation
-- - Full foreign key constraints, indexes, and row-level security policies
-- ============================================================================

BEGIN;

-- ============================================================================
-- MISSING WORKFLOW ORCHESTRATION TABLES
-- ============================================================================

-- Workflow Templates (AI workflow definitions)
CREATE TABLE IF NOT EXISTS workflow_templates (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    tenant_id INTEGER, -- Will be synced with organization_id

    -- Template definition
    name VARCHAR(255) NOT NULL,
    description TEXT,
    workflow_type VARCHAR(100) NOT NULL, -- 'prospect_discovery', 'email_campaign', 'connection_mapping'
    version VARCHAR(20) DEFAULT '1.0.0',

    -- Workflow configuration
    workflow_definition JSONB NOT NULL DEFAULT '{}', -- JSON workflow graph
    default_parameters JSONB DEFAULT '{}',
    timeout_minutes INTEGER DEFAULT 60,
    max_retries INTEGER DEFAULT 3,

    -- Status and metadata
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'deprecated', 'draft')),
    is_system_template BOOLEAN DEFAULT false,
    requires_approval BOOLEAN DEFAULT false,

    -- Audit fields
    created_by INTEGER REFERENCES team_members(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_org_template_name UNIQUE (organization_id, name),
    CONSTRAINT workflow_templates_tenant_org_match CHECK (tenant_id = organization_id)
);

-- Workflow Executions (tracking workflow runs)
CREATE TABLE IF NOT EXISTS workflow_executions (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    tenant_id INTEGER, -- Will be synced with organization_id

    -- Execution identity
    execution_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    template_id INTEGER REFERENCES workflow_templates(id) ON DELETE SET NULL,
    workflow_type VARCHAR(100) NOT NULL,

    -- Execution context
    triggered_by INTEGER REFERENCES team_members(id) ON DELETE SET NULL,
    trigger_source VARCHAR(100) DEFAULT 'manual', -- 'manual', 'scheduled', 'webhook', 'api'
    parent_execution_id UUID REFERENCES workflow_executions(execution_id) ON DELETE CASCADE,

    -- Execution parameters
    input_parameters JSONB DEFAULT '{}',
    runtime_config JSONB DEFAULT '{}',

    -- Status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'running', 'paused', 'completed', 'failed', 'cancelled', 'timeout'
    )),
    progress_percentage DECIMAL(5,2) DEFAULT 0.00 CHECK (progress_percentage >= 0 AND progress_percentage <= 100),
    current_node VARCHAR(255),

    -- Results and error handling
    output_data JSONB DEFAULT '{}',
    error_message TEXT,
    error_details JSONB,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    timeout_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Resource tracking
    execution_time_seconds DECIMAL(10,3) DEFAULT 0.0,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    -- Constraint
    CONSTRAINT workflow_executions_tenant_org_match CHECK (tenant_id = organization_id)
);

-- Workflow Node Executions (granular step tracking)
CREATE TABLE IF NOT EXISTS workflow_node_executions (
    id SERIAL PRIMARY KEY,
    execution_id INTEGER NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,

    -- Node identity
    node_id VARCHAR(255) NOT NULL,
    node_type VARCHAR(100) NOT NULL, -- 'ai_agent', 'api_call', 'data_transform', 'human_approval'
    node_name VARCHAR(255) NOT NULL,

    -- Execution tracking
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'running', 'completed', 'failed', 'skipped', 'retrying'
    )),
    attempt_number INTEGER DEFAULT 1,

    -- Node data
    input_data JSONB DEFAULT '{}',
    output_data JSONB DEFAULT '{}',
    error_message TEXT,
    error_details JSONB,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    execution_time_seconds DECIMAL(8,3) DEFAULT 0.0,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_execution_node UNIQUE (execution_id, node_id, attempt_number)
);

-- ============================================================================
-- MISSING CORE FUNCTIONALITY TABLES
-- ============================================================================

-- Interactions (contact relationship scoring)
CREATE TABLE IF NOT EXISTS interactions (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
    tenant_id INTEGER, -- For backward compatibility

    -- Contact reference
    contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
    team_member_id INTEGER REFERENCES team_members(id) ON DELETE SET NULL,

    -- Interaction details
    channel VARCHAR(50) NOT NULL CHECK (channel IN (
        'linkedin_message', 'linkedin_comment', 'linkedin_reaction', 'email',
        'phone_call', 'meeting', 'coffee_chat', 'event', 'referral', 'other'
    )),
    interaction_type VARCHAR(100) NOT NULL CHECK (interaction_type IN (
        'outbound_message', 'inbound_message', 'mutual_connection', 'endorsement',
        'recommendation', 'content_engagement', 'meeting_scheduled', 'introduction_made'
    )),
    direction VARCHAR(20) DEFAULT 'outbound' CHECK (direction IN ('inbound', 'outbound', 'mutual')),

    -- Content and context
    subject VARCHAR(500),
    content_preview TEXT,
    interaction_context JSONB DEFAULT '{}', -- Rich context data

    -- Scoring and impact
    strength_impact DECIMAL(3,2) DEFAULT 0.0 CHECK (strength_impact >= -1.0 AND strength_impact <= 1.0),
    relationship_score_before DECIMAL(5,2),
    relationship_score_after DECIMAL(5,2),

    -- Timing and metadata
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    notes TEXT,
    source VARCHAR(100) DEFAULT 'manual', -- 'manual', 'linkedin_scraper', 'email_tracking'

    -- Audit fields
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Daily Metrics (analytics dashboard data)
CREATE TABLE IF NOT EXISTS daily_metrics (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    tenant_id INTEGER, -- For backward compatibility

    -- Metric identification
    metric_date DATE NOT NULL,
    metric_category VARCHAR(100) NOT NULL, -- 'prospects', 'connections', 'emails', 'workflows'
    metric_name VARCHAR(100) NOT NULL,

    -- Metric values
    metric_value DECIMAL(15,4) NOT NULL,
    metric_count INTEGER DEFAULT 0,
    metric_percentage DECIMAL(5,2),

    -- Dimensional data
    dimensions JSONB DEFAULT '{}', -- Flexible dimensions like {team_member_id: 123, campaign_id: 456}
    metadata JSONB DEFAULT '{}',

    -- Aggregation level
    aggregation_level VARCHAR(50) DEFAULT 'daily' CHECK (aggregation_level IN ('hourly', 'daily', 'weekly', 'monthly')),

    -- Audit fields
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_org_metric_date UNIQUE (organization_id, metric_date, metric_category, metric_name, dimensions)
);

-- Email Logs (comprehensive email tracking)
CREATE TABLE IF NOT EXISTS email_logs (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    tenant_id INTEGER, -- For backward compatibility

    -- Email identification
    email_id VARCHAR(255) UNIQUE, -- External provider email ID
    message_id VARCHAR(255), -- SMTP Message-ID header
    thread_id VARCHAR(255), -- Email thread identifier

    -- Email routing
    sender_email VARCHAR(255) NOT NULL,
    sender_name VARCHAR(255),
    recipient_email VARCHAR(255) NOT NULL,
    cc_emails TEXT[], -- Array of CC recipients
    bcc_emails TEXT[], -- Array of BCC recipients

    -- Email content
    subject TEXT,
    body_text TEXT,
    body_html TEXT,
    attachments JSONB DEFAULT '[]', -- Array of attachment metadata

    -- Email classification
    email_type VARCHAR(100) NOT NULL DEFAULT 'introduction' CHECK (email_type IN (
        'introduction', 'follow_up', 'thank_you', 'meeting_request', 'proposal', 'other'
    )),
    campaign_id INTEGER, -- Reference to email campaign
    prospect_id INTEGER REFERENCES prospects(id) ON DELETE SET NULL,
    email_job_id INTEGER REFERENCES email_jobs(id) ON DELETE SET NULL,

    -- Delivery tracking
    status VARCHAR(50) NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'sending', 'sent', 'delivered', 'opened', 'clicked',
        'replied', 'bounced', 'spam', 'failed', 'cancelled'
    )),
    provider VARCHAR(50), -- 'sendgrid', 'mailgun', 'ses'
    provider_status VARCHAR(100),
    provider_response JSONB,

    -- Engagement tracking
    opened_count INTEGER DEFAULT 0,
    clicked_count INTEGER DEFAULT 0,
    first_opened_at TIMESTAMP WITH TIME ZONE,
    first_clicked_at TIMESTAMP WITH TIME ZONE,
    replied_at TIMESTAMP WITH TIME ZONE,

    -- Cost and billing
    email_cost DECIMAL(10,4) DEFAULT 0.0000,
    cost_currency VARCHAR(3) DEFAULT 'USD',

    -- Timing
    scheduled_at TIMESTAMP WITH TIME ZONE,
    sent_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,

    -- Audit fields
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Error handling
    error_message TEXT,
    error_code VARCHAR(50),
    retry_count INTEGER DEFAULT 0
);

-- ============================================================================
-- ADD MISSING COLUMNS
-- ============================================================================

-- Add tenant_id to agent_decisions if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'agent_decisions' AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE agent_decisions ADD COLUMN tenant_id INTEGER;

        -- Backfill tenant_id with organization_id
        UPDATE agent_decisions SET tenant_id = organization_id WHERE tenant_id IS NULL;

        -- Add constraint to ensure they match
        ALTER TABLE agent_decisions
            ADD CONSTRAINT agent_decisions_tenant_org_match CHECK (tenant_id = organization_id);
    END IF;
END;
$$;

-- Add tenant_id to approval_requests if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'approval_requests' AND column_name = 'tenant_id'
    ) THEN
        ALTER TABLE approval_requests ADD COLUMN tenant_id INTEGER;

        -- Backfill tenant_id with organization_id
        UPDATE approval_requests SET tenant_id = organization_id WHERE tenant_id IS NULL;

        -- Add constraint to ensure they match
        ALTER TABLE approval_requests
            ADD CONSTRAINT approval_requests_tenant_org_match CHECK (tenant_id = organization_id);
    END IF;
END;
$$;

-- ============================================================================
-- CREATE INDEXES FOR PERFORMANCE
-- ============================================================================

-- Workflow Templates indexes
CREATE INDEX IF NOT EXISTS idx_workflow_templates_org ON workflow_templates(organization_id);
CREATE INDEX IF NOT EXISTS idx_workflow_templates_type ON workflow_templates(workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_templates_status ON workflow_templates(status);
CREATE INDEX IF NOT EXISTS idx_workflow_templates_created ON workflow_templates(created_at);

-- Workflow Executions indexes
CREATE INDEX IF NOT EXISTS idx_workflow_executions_org ON workflow_executions(organization_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_template ON workflow_executions(template_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_status ON workflow_executions(status);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_type ON workflow_executions(workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_started ON workflow_executions(started_at);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_parent ON workflow_executions(parent_execution_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_triggered_by ON workflow_executions(triggered_by);

-- Workflow Node Executions indexes
CREATE INDEX IF NOT EXISTS idx_workflow_node_executions_execution ON workflow_node_executions(execution_id);
CREATE INDEX IF NOT EXISTS idx_workflow_node_executions_status ON workflow_node_executions(status);
CREATE INDEX IF NOT EXISTS idx_workflow_node_executions_type ON workflow_node_executions(node_type);
CREATE INDEX IF NOT EXISTS idx_workflow_node_executions_started ON workflow_node_executions(started_at);

-- Interactions indexes
CREATE INDEX IF NOT EXISTS idx_interactions_org ON interactions(organization_id);
CREATE INDEX IF NOT EXISTS idx_interactions_contact ON interactions(contact_id);
CREATE INDEX IF NOT EXISTS idx_interactions_team_member ON interactions(team_member_id);
CREATE INDEX IF NOT EXISTS idx_interactions_channel ON interactions(channel);
CREATE INDEX IF NOT EXISTS idx_interactions_occurred ON interactions(occurred_at);
CREATE INDEX IF NOT EXISTS idx_interactions_strength ON interactions(strength_impact);

-- Daily Metrics indexes
CREATE INDEX IF NOT EXISTS idx_daily_metrics_org_date ON daily_metrics(organization_id, metric_date);
CREATE INDEX IF NOT EXISTS idx_daily_metrics_category ON daily_metrics(metric_category);
CREATE INDEX IF NOT EXISTS idx_daily_metrics_name ON daily_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_daily_metrics_calculated ON daily_metrics(calculated_at);

-- Email Logs indexes
CREATE INDEX IF NOT EXISTS idx_email_logs_org ON email_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_recipient ON email_logs(recipient_email);
CREATE INDEX IF NOT EXISTS idx_email_logs_sender ON email_logs(sender_email);
CREATE INDEX IF NOT EXISTS idx_email_logs_status ON email_logs(status);
CREATE INDEX IF NOT EXISTS idx_email_logs_type ON email_logs(email_type);
CREATE INDEX IF NOT EXISTS idx_email_logs_sent ON email_logs(sent_at);
CREATE INDEX IF NOT EXISTS idx_email_logs_prospect ON email_logs(prospect_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_job ON email_logs(email_job_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_message_id ON email_logs(message_id);

-- ============================================================================
-- ROW-LEVEL SECURITY POLICIES
-- ============================================================================

-- Enable RLS on new tables
ALTER TABLE workflow_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_templates FORCE ROW LEVEL SECURITY;

ALTER TABLE workflow_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_executions FORCE ROW LEVEL SECURITY;

ALTER TABLE interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE interactions FORCE ROW LEVEL SECURITY;

ALTER TABLE daily_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_metrics FORCE ROW LEVEL SECURITY;

ALTER TABLE email_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_logs FORCE ROW LEVEL SECURITY;

-- Create organization isolation policies
CREATE POLICY workflow_templates_org_isolation ON workflow_templates
    USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);

CREATE POLICY workflow_executions_org_isolation ON workflow_executions
    USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);

CREATE POLICY workflow_node_executions_org_isolation ON workflow_node_executions
    USING (
        EXISTS (
            SELECT 1 FROM workflow_executions we
            WHERE we.id = workflow_node_executions.execution_id
              AND we.organization_id = current_setting('app.current_organization_id', true)::INTEGER
        )
    );

CREATE POLICY interactions_org_isolation ON interactions
    USING (
        organization_id = current_setting('app.current_organization_id', true)::INTEGER
        OR organization_id IS NULL -- Allow access to legacy data without org_id
    );

CREATE POLICY daily_metrics_org_isolation ON daily_metrics
    USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);

CREATE POLICY email_logs_org_isolation ON email_logs
    USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);

-- ============================================================================
-- UPDATE STATISTICS AND VALIDATE
-- ============================================================================

-- Analyze new tables for query optimization
ANALYZE workflow_templates;
ANALYZE workflow_executions;
ANALYZE workflow_node_executions;
ANALYZE interactions;
ANALYZE daily_metrics;
ANALYZE email_logs;

-- Verify all constraints are properly created
DO $$
DECLARE
    constraint_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO constraint_count
    FROM information_schema.table_constraints
    WHERE table_schema = 'public'
      AND constraint_type = 'FOREIGN KEY'
      AND table_name IN ('workflow_templates', 'workflow_executions', 'workflow_node_executions', 'interactions', 'daily_metrics', 'email_logs');

    IF constraint_count < 8 THEN
        RAISE WARNING 'Expected at least 8 foreign key constraints on new tables, found %', constraint_count;
    END IF;
END;
$$;

COMMIT;

-- ============================================================================
-- POST-MIGRATION VERIFICATION
-- ============================================================================

-- Verify all tables exist
SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workflow_templates') THEN '✓'
        ELSE '✗'
    END as workflow_templates,
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workflow_executions') THEN '✓'
        ELSE '✗'
    END as workflow_executions,
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'workflow_node_executions') THEN '✓'
        ELSE '✗'
    END as workflow_node_executions,
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'interactions') THEN '✓'
        ELSE '✗'
    END as interactions,
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'daily_metrics') THEN '✓'
        ELSE '✗'
    END as daily_metrics,
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'email_logs') THEN '✓'
        ELSE '✗'
    END as email_logs;

-- Verify missing columns are added
SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'agent_decisions' AND column_name = 'tenant_id') THEN '✓'
        ELSE '✗'
    END as agent_decisions_tenant_id,
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'approval_requests' AND column_name = 'tenant_id') THEN '✓'
        ELSE '✗'
    END as approval_requests_tenant_id;