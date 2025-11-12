-- ============================================================================
-- Migration 017: Targeted Schema Fixes (Production Safe)
-- ============================================================================
-- Safe, incremental fix for critical database schema gaps.
-- Focuses only on missing elements that don't conflict with existing data.
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. CREATE MISSING CRITICAL TABLES
-- ============================================================================

-- Email Metrics Table - Email performance tracking
CREATE TABLE IF NOT EXISTS email_metrics (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL,

    -- Metric tracking
    metric_type VARCHAR(50) NOT NULL CHECK (metric_type IN (
        'sent', 'delivered', 'opened', 'clicked', 'replied', 'bounced', 'unsubscribed'
    )),
    metric_date DATE NOT NULL,
    count INTEGER DEFAULT 1,

    -- Email details
    campaign_id VARCHAR(255),
    subject VARCHAR(500),
    provider VARCHAR(50),

    -- Timing
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_email_metric UNIQUE (contact_id, tenant_id, metric_type, metric_date, campaign_id)
);

-- Introductions Table - Introduction tracking system
CREATE TABLE IF NOT EXISTS introductions (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,

    -- Introduction parties (using existing ID references)
    prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,

    -- Introduction details
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'sent', 'accepted', 'declined', 'completed', 'failed'
    )),
    message TEXT,
    linkedin_url VARCHAR(500),

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Team Networks Table - Team member network data
CREATE TABLE IF NOT EXISTS team_networks (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    team_member_id INTEGER NOT NULL REFERENCES team_members(id) ON DELETE CASCADE,

    -- Network data
    network_data JSONB NOT NULL DEFAULT '{}',
    total_connections INTEGER DEFAULT 0,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_team_member_network UNIQUE (tenant_id, team_member_id)
);

-- Provider Instances Table - Service provider management
CREATE TABLE IF NOT EXISTS provider_instances (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,

    -- Provider details
    provider VARCHAR(100) NOT NULL,
    instance_name VARCHAR(255) NOT NULL,
    instance_data JSONB NOT NULL DEFAULT '{}',

    -- Status
    is_active BOOLEAN DEFAULT true,

    -- Audit
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_provider_instance UNIQUE (tenant_id, provider, instance_name)
);

-- ============================================================================
-- 2. ADD CRITICAL MISSING COLUMNS
-- ============================================================================

-- Add missing columns to prospects table
DO $$
BEGIN
    -- Add email_confidence column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'prospects' AND column_name = 'email_confidence') THEN
        ALTER TABLE prospects ADD COLUMN email_confidence DECIMAL(3,2) CHECK (email_confidence >= 0.0 AND email_confidence <= 1.0);
    END IF;

    -- Add status column if missing (careful not to conflict with prospects_new.status)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'prospects' AND column_name = 'status') THEN
        ALTER TABLE prospects ADD COLUMN status VARCHAR(50) DEFAULT 'active' CHECK (status IN (
            'active', 'contacted', 'responded', 'converted', 'unqualified', 'do_not_contact'
        ));
    END IF;
END;
$$;

-- Add missing columns to team_members table
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
    END IF;
END;
$$;

-- Add missing columns to job_runs table
DO $$
BEGIN
    -- Add cached_result column if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'job_runs' AND column_name = 'cached_result') THEN
        ALTER TABLE job_runs ADD COLUMN cached_result JSONB DEFAULT '{}';
    END IF;
END;
$$;

-- ============================================================================
-- 3. ADD CRITICAL FOREIGN KEY CONSTRAINTS
-- ============================================================================

-- Add FK constraints where both tables exist
DO $$
BEGIN
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
END;
$$;

-- ============================================================================
-- 4. ADD PERFORMANCE INDEXES
-- ============================================================================

-- Create missing performance indexes
CREATE INDEX IF NOT EXISTS idx_job_runs_job_type ON job_runs(job_type);
CREATE INDEX IF NOT EXISTS idx_job_runs_user_id ON job_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_user_id ON workflow_contexts(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_user_id ON workflow_states(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_workflow_type ON workflow_states(workflow_type);

-- Indexes for new tables
CREATE INDEX IF NOT EXISTS idx_email_metrics_tenant_date ON email_metrics(tenant_id, metric_date);
CREATE INDEX IF NOT EXISTS idx_email_metrics_contact ON email_metrics(contact_id);
CREATE INDEX IF NOT EXISTS idx_introductions_tenant_status ON introductions(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_team_networks_tenant_member ON team_networks(tenant_id, team_member_id);
CREATE INDEX IF NOT EXISTS idx_provider_instances_tenant_provider ON provider_instances(tenant_id, provider);

-- ============================================================================
-- 5. IMPLEMENT ROW-LEVEL SECURITY (SAFE APPROACH)
-- ============================================================================

-- Enable RLS on new tables
ALTER TABLE email_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_metrics FORCE ROW LEVEL SECURITY;
CREATE POLICY email_metrics_tenant_isolation ON email_metrics
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE introductions ENABLE ROW LEVEL SECURITY;
ALTER TABLE introductions FORCE ROW LEVEL SECURITY;
CREATE POLICY introductions_tenant_isolation ON introductions
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE team_networks ENABLE ROW LEVEL SECURITY;
ALTER TABLE team_networks FORCE ROW LEVEL SECURITY;
CREATE POLICY team_networks_tenant_isolation ON team_networks
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

ALTER TABLE provider_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_instances FORCE ROW LEVEL SECURITY;
CREATE POLICY provider_instances_tenant_isolation ON provider_instances
    USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);

-- Enable RLS on existing critical tables (only if not already enabled)
DO $$
BEGIN
    -- Prospects table (legacy schema uses tenant_id)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'prospects') THEN
        -- Check if RLS is already enabled
        IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'prospects' AND relrowsecurity = true) THEN
            ALTER TABLE prospects ENABLE ROW LEVEL SECURITY;
            ALTER TABLE prospects FORCE ROW LEVEL SECURITY;
        END IF;
        -- Create policy if it doesn't exist
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'prospects' AND policyname = 'prospects_tenant_isolation') THEN
            CREATE POLICY prospects_tenant_isolation ON prospects
                USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
        END IF;
    END IF;

    -- Job runs table
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'job_runs') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'job_runs' AND relrowsecurity = true) THEN
            ALTER TABLE job_runs ENABLE ROW LEVEL SECURITY;
            ALTER TABLE job_runs FORCE ROW LEVEL SECURITY;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'job_runs' AND policyname = 'job_runs_tenant_isolation') THEN
            CREATE POLICY job_runs_tenant_isolation ON job_runs
                USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
        END IF;
    END IF;

    -- LinkedIn sessions table
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'linkedin_sessions') THEN
        IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'linkedin_sessions' AND relrowsecurity = true) THEN
            ALTER TABLE linkedin_sessions ENABLE ROW LEVEL SECURITY;
            ALTER TABLE linkedin_sessions FORCE ROW LEVEL SECURITY;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'linkedin_sessions' AND policyname = 'linkedin_sessions_tenant_isolation') THEN
            CREATE POLICY linkedin_sessions_tenant_isolation ON linkedin_sessions
                USING (tenant_id = current_setting('app.current_tenant_id', true)::INTEGER);
        END IF;
    END IF;
END;
$$;

-- ============================================================================
-- 6. VALIDATE AND ANALYZE
-- ============================================================================

-- Update table statistics for query optimization
ANALYZE email_metrics;
ANALYZE introductions;
ANALYZE team_networks;
ANALYZE provider_instances;

-- Validation check
DO $$
DECLARE
    new_table_count INTEGER;
    total_tables INTEGER;
    total_policies INTEGER;
BEGIN
    -- Count new tables created
    SELECT COUNT(*) INTO new_table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN ('email_metrics', 'introductions', 'team_networks', 'provider_instances');

    -- Count total tables
    SELECT COUNT(*) INTO total_tables
    FROM information_schema.tables
    WHERE table_schema = 'public';

    -- Count RLS policies
    SELECT COUNT(*) INTO total_policies
    FROM pg_policies
    WHERE schemaname = 'public';

    RAISE NOTICE 'Migration completed successfully:';
    RAISE NOTICE '- New tables created: %', new_table_count;
    RAISE NOTICE '- Total tables: %', total_tables;
    RAISE NOTICE '- Total RLS policies: %', total_policies;
END;
$$;

COMMIT;

-- ============================================================================
-- POST-MIGRATION VERIFICATION
-- ============================================================================

-- Verify new tables were created
SELECT
    'CRITICAL TABLES CREATED:' as status,
    CASE WHEN COUNT(*) = 4 THEN '✓ SUCCESS (4/4 CREATED)'
         ELSE CONCAT('✗ MISSING: ', 4 - COUNT(*)) END as result
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('email_metrics', 'introductions', 'team_networks', 'provider_instances');

-- Verify columns were added
SELECT
    'CRITICAL COLUMNS ADDED:' as status,
    CASE WHEN COUNT(*) >= 6 THEN '✓ SUCCESS'
         ELSE CONCAT('✗ MISSING COLUMNS') END as result
FROM information_schema.columns
WHERE table_schema = 'public'
  AND ((table_name = 'prospects' AND column_name IN ('email_confidence', 'status'))
    OR (table_name = 'team_members' AND column_name IN ('active', 'position', 'tenant_id', 'user_id'))
    OR (table_name = 'job_runs' AND column_name = 'cached_result'));

-- Final summary
SELECT
    (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public') as total_tables,
    (SELECT COUNT(*) FROM information_schema.referential_constraints WHERE constraint_schema = 'public') as total_foreign_keys,
    (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public') as total_indexes,
    (SELECT COUNT(*) FROM pg_policies WHERE schemaname = 'public') as total_rls_policies;