-- Database Performance Indexes for Existing Schema
-- Only create indexes for columns that actually exist

-- Check existing schema and create indexes accordingly

-- PROSPECTS TABLE INDEXES (for existing columns)
CREATE INDEX IF NOT EXISTS idx_prospects_company_safe ON prospects(company);
CREATE INDEX IF NOT EXISTS idx_prospects_linkedin_url_safe ON prospects(linkedin_url);
CREATE INDEX IF NOT EXISTS idx_prospects_created_at_safe ON prospects(created_at);
CREATE INDEX IF NOT EXISTS idx_prospects_updated_at_safe ON prospects(updated_at);
CREATE INDEX IF NOT EXISTS idx_prospects_full_name_safe ON prospects(full_name);

-- CONNECTORS TABLE INDEXES
CREATE INDEX IF NOT EXISTS idx_connectors_linkedin_url_safe ON connectors(linkedin_url);
CREATE INDEX IF NOT EXISTS idx_connectors_full_name_safe ON connectors(full_name);
CREATE INDEX IF NOT EXISTS idx_connectors_created_at_safe ON connectors(created_at);

-- PROSPECT_CONNECTORS TABLE INDEXES
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_prospect_id_safe ON prospect_connectors(prospect_id);
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_connector_id_safe ON prospect_connectors(connector_id);
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_ranking_score_safe ON prospect_connectors(ranking_score);
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_rank_safe ON prospect_connectors(rank);

-- TEAM_MEMBERS TABLE INDEXES
CREATE INDEX IF NOT EXISTS idx_team_members_organization_id_safe ON team_members(organization_id);
CREATE INDEX IF NOT EXISTS idx_team_members_email_safe ON team_members(email);
CREATE INDEX IF NOT EXISTS idx_team_members_created_at_safe ON team_members(created_at);

-- AUDIT_EVENTS TABLE INDEXES (if exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_events') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_audit_events_organization_id_safe ON audit_events(organization_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_audit_events_created_at_safe ON audit_events(created_at)';
    END IF;
END $$;

-- INTEGRATION_SETS TABLE INDEXES (if exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'integration_sets') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_integration_sets_organization_id_safe ON integration_sets(organization_id)';
    END IF;
END $$;

-- COOKIE_JARS TABLE INDEXES (if exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cookie_jars') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_cookie_jars_tenant_id_safe ON cookie_jars(tenant_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_cookie_jars_name_safe ON cookie_jars(name)';
    END IF;
END $$;

-- JOB_IDEMPOTENCY TABLE INDEXES
CREATE INDEX IF NOT EXISTS idx_job_idempotency_created_at_safe ON job_idempotency(created_at);

-- APPROVAL_REQUESTS TABLE INDEXES
CREATE INDEX IF NOT EXISTS idx_approval_requests_organization_id_safe ON approval_requests(organization_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_created_at_safe ON approval_requests(created_at);

-- Expression indexes for case-insensitive search
CREATE INDEX IF NOT EXISTS idx_prospects_company_lower_safe ON prospects(LOWER(company));
CREATE INDEX IF NOT EXISTS idx_prospects_name_lower_safe ON prospects(LOWER(full_name));
CREATE INDEX IF NOT EXISTS idx_connectors_company_lower_safe ON connectors(LOWER(company));
CREATE INDEX IF NOT EXISTS idx_connectors_name_lower_safe ON connectors(LOWER(full_name));

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_prospect_rank_safe ON prospect_connectors(prospect_id, rank);

-- Add comments to describe index purposes
COMMENT ON INDEX idx_prospects_company_safe IS 'Optimizes company-based prospect searches';
COMMENT ON INDEX idx_prospect_connectors_prospect_rank_safe IS 'Optimizes prospect connector ranking queries';
COMMENT ON INDEX idx_approval_requests_organization_id_safe IS 'Optimizes approval queue processing by organization';

-- Update table statistics for better query planning
ANALYZE prospects;
ANALYZE connectors;
ANALYZE prospect_connectors;
ANALYZE team_members;
ANALYZE approval_requests;
ANALYZE job_idempotency;