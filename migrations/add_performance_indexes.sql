-- Database Performance Indexes Migration
-- Adds comprehensive indexes to improve query performance for high-traffic operations

-- ============================================================================
-- PROSPECTS TABLE INDEXES
-- ============================================================================

-- Index for organization-based prospect queries (most common access pattern)
CREATE INDEX IF NOT EXISTS idx_prospects_organization_id ON prospects(organization_id);

-- Index for prospect status filtering
CREATE INDEX IF NOT EXISTS idx_prospects_status ON prospects(status);

-- Composite index for organization + status queries (very common)
CREATE INDEX IF NOT EXISTS idx_prospects_org_status ON prospects(organization_id, status);

-- Index for prospect search by company
CREATE INDEX IF NOT EXISTS idx_prospects_company ON prospects(company);

-- Index for LinkedIn URL lookups
CREATE INDEX IF NOT EXISTS idx_prospects_linkedin_url ON prospects(linkedin_url);

-- Index for email-based queries
CREATE INDEX IF NOT EXISTS idx_prospects_email ON prospects(email);

-- Index for created/updated timestamp queries
CREATE INDEX IF NOT EXISTS idx_prospects_created_at ON prospects(created_at);
CREATE INDEX IF NOT EXISTS idx_prospects_updated_at ON prospects(updated_at);

-- ============================================================================
-- CONNECTORS TABLE INDEXES
-- ============================================================================

-- Index for organization-based connector queries
CREATE INDEX IF NOT EXISTS idx_connectors_organization_id ON connectors(organization_id);

-- Index for LinkedIn URL lookups
CREATE INDEX IF NOT EXISTS idx_connectors_linkedin_url ON connectors(linkedin_url);

-- Index for email-based connector queries
CREATE INDEX IF NOT EXISTS idx_connectors_email ON connectors(email);

-- Index for company-based connector search
CREATE INDEX IF NOT EXISTS idx_connectors_company ON connectors(company);

-- ============================================================================
-- PROSPECT_CONNECTORS TABLE INDEXES
-- ============================================================================

-- Primary composite index for prospect-connector relationships
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_prospect_id ON prospect_connectors(prospect_id);
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_connector_id ON prospect_connectors(connector_id);

-- Composite index for prospect + ranking queries
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_prospect_rank ON prospect_connectors(prospect_id, rank);

-- Index for ranking score filtering
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_ranking_score ON prospect_connectors(ranking_score);

-- Index for team member assignment
CREATE INDEX IF NOT EXISTS idx_prospect_connectors_team_member_id ON prospect_connectors(team_member_id);

-- ============================================================================
-- TEAM_MEMBERS TABLE INDEXES
-- ============================================================================

-- Index for organization-based team member queries
CREATE INDEX IF NOT EXISTS idx_team_members_organization_id ON team_members(organization_id);

-- Index for user authentication
CREATE INDEX IF NOT EXISTS idx_team_members_user_id ON team_members(user_id);

-- Index for email-based lookups
CREATE INDEX IF NOT EXISTS idx_team_members_email ON team_members(email);

-- Index for active/inactive team members
CREATE INDEX IF NOT EXISTS idx_team_members_active ON team_members(active);

-- Composite index for organization + active queries
CREATE INDEX IF NOT EXISTS idx_team_members_org_active ON team_members(organization_id, active);

-- ============================================================================
-- EMAIL AND COMMUNICATION INDEXES
-- ============================================================================

-- Index for email metrics by contact
CREATE INDEX IF NOT EXISTS idx_email_metrics_contact_id ON email_metrics(contact_id);
CREATE INDEX IF NOT EXISTS idx_email_metrics_tenant_id ON email_metrics(tenant_id);

-- Composite index for tenant + contact email metrics
CREATE INDEX IF NOT EXISTS idx_email_metrics_tenant_contact ON email_metrics(tenant_id, contact_id);

-- Index for email job processing
CREATE INDEX IF NOT EXISTS idx_email_jobs_organization_id ON email_jobs(organization_id);
CREATE INDEX IF NOT EXISTS idx_email_jobs_status ON email_jobs(status);
CREATE INDEX IF NOT EXISTS idx_email_jobs_created_at ON email_jobs(created_at);

-- Composite index for job queue processing
CREATE INDEX IF NOT EXISTS idx_email_jobs_org_status_created ON email_jobs(organization_id, status, created_at);

-- ============================================================================
-- APPROVAL AND WORKFLOW INDEXES
-- ============================================================================

-- Index for approval requests by organization
CREATE INDEX IF NOT EXISTS idx_approval_requests_organization_id ON approval_requests(organization_id);

-- Index for approval status
CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);

-- Index for approval type filtering
CREATE INDEX IF NOT EXISTS idx_approval_requests_approval_type ON approval_requests(approval_type);

-- Composite index for organization + status queries
CREATE INDEX IF NOT EXISTS idx_approval_requests_org_status ON approval_requests(organization_id, status);

-- Index for requester-based queries
CREATE INDEX IF NOT EXISTS idx_approval_requests_requester_id ON approval_requests(requester_id);

-- Index for creation timestamp (for queue processing)
CREATE INDEX IF NOT EXISTS idx_approval_requests_created_at ON approval_requests(created_at);

-- ============================================================================
-- AUDIT AND LOGGING INDEXES
-- ============================================================================

-- Index for audit events by organization
CREATE INDEX IF NOT EXISTS idx_audit_events_organization_id ON audit_events(organization_id);

-- Index for audit event types
CREATE INDEX IF NOT EXISTS idx_audit_events_event_type ON audit_events(event_type);

-- Index for user-based audit queries
CREATE INDEX IF NOT EXISTS idx_audit_events_user_id ON audit_events(user_id);

-- Index for timestamp-based audit queries
CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp ON audit_events(timestamp);

-- Composite index for organization + event type queries
CREATE INDEX IF NOT EXISTS idx_audit_events_org_type ON audit_events(organization_id, event_type);

-- ============================================================================
-- INTEGRATION AND API INDEXES
-- ============================================================================

-- Index for integration sets by organization
CREATE INDEX IF NOT EXISTS idx_integration_sets_organization_id ON integration_sets(organization_id);

-- Index for integration set status
CREATE INDEX IF NOT EXISTS idx_integration_sets_status ON integration_sets(status);

-- Index for cookie jars by tenant
CREATE INDEX IF NOT EXISTS idx_cookie_jars_tenant_id ON cookie_jars(tenant_id);

-- Index for cookie jar names
CREATE INDEX IF NOT EXISTS idx_cookie_jars_name ON cookie_jars(name);

-- ============================================================================
-- JOB AND QUEUE INDEXES
-- ============================================================================

-- Index for job idempotency by organization
CREATE INDEX IF NOT EXISTS idx_job_idempotency_organization_id ON job_idempotency(organization_id);

-- Index for idempotency key lookups
CREATE INDEX IF NOT EXISTS idx_job_idempotency_key ON job_idempotency(idempotency_key);

-- Index for job creation timestamps
CREATE INDEX IF NOT EXISTS idx_job_idempotency_created_at ON job_idempotency(created_at);

-- ============================================================================
-- ORGANIZATION METRICS INDEXES
-- ============================================================================

-- Index for organization metrics by organization
CREATE INDEX IF NOT EXISTS idx_organization_metrics_organization_id ON organization_metrics(organization_id);

-- Index for metric types
CREATE INDEX IF NOT EXISTS idx_organization_metrics_metric_type ON organization_metrics(metric_type);

-- Index for metric timestamps
CREATE INDEX IF NOT EXISTS idx_organization_metrics_timestamp ON organization_metrics(timestamp);

-- Composite index for organization + metric type + timestamp queries
CREATE INDEX IF NOT EXISTS idx_organization_metrics_org_type_time ON organization_metrics(organization_id, metric_type, timestamp);

-- ============================================================================
-- PARTIAL INDEXES FOR PERFORMANCE
-- ============================================================================

-- Partial index for active prospects only
CREATE INDEX IF NOT EXISTS idx_prospects_active ON prospects(organization_id, created_at)
WHERE status IN ('new', 'contacted', 'qualified');

-- Partial index for pending approvals only
CREATE INDEX IF NOT EXISTS idx_approval_requests_pending ON approval_requests(organization_id, created_at)
WHERE status = 'pending';

-- Partial index for recent email jobs
CREATE INDEX IF NOT EXISTS idx_email_jobs_recent ON email_jobs(organization_id, status)
WHERE created_at > CURRENT_DATE - INTERVAL '30 days';

-- Partial index for high-confidence email addresses
CREATE INDEX IF NOT EXISTS idx_prospects_high_confidence_email ON prospects(organization_id, email)
WHERE email IS NOT NULL AND email_confidence > 0.8;

-- ============================================================================
-- COVERING INDEXES FOR COMMON QUERIES
-- ============================================================================

-- Covering index for prospect list queries
CREATE INDEX IF NOT EXISTS idx_prospects_list_covering ON prospects(organization_id, status)
INCLUDE (id, full_name, company, email, linkedin_url, created_at);

-- Covering index for connector list queries
CREATE INDEX IF NOT EXISTS idx_connectors_list_covering ON connectors(organization_id)
INCLUDE (id, full_name, company, linkedin_url, headline);

-- Covering index for team member list queries
CREATE INDEX IF NOT EXISTS idx_team_members_list_covering ON team_members(organization_id, active)
INCLUDE (id, name, email, role, created_at);

-- ============================================================================
-- EXPRESSION INDEXES FOR SEARCH
-- ============================================================================

-- Case-insensitive search indexes
CREATE INDEX IF NOT EXISTS idx_prospects_company_lower ON prospects(organization_id, LOWER(company));
CREATE INDEX IF NOT EXISTS idx_prospects_name_lower ON prospects(organization_id, LOWER(full_name));
CREATE INDEX IF NOT EXISTS idx_connectors_company_lower ON connectors(organization_id, LOWER(company));
CREATE INDEX IF NOT EXISTS idx_connectors_name_lower ON connectors(organization_id, LOWER(full_name));

-- ============================================================================
-- CLEANUP COMMENTS
-- ============================================================================

-- Add comments to describe index purposes
COMMENT ON INDEX idx_prospects_org_status IS 'Optimizes organization + status filtering queries';
COMMENT ON INDEX idx_prospect_connectors_prospect_rank IS 'Optimizes prospect connector ranking queries';
COMMENT ON INDEX idx_approval_requests_org_status IS 'Optimizes approval queue processing';
COMMENT ON INDEX idx_email_jobs_org_status_created IS 'Optimizes email job queue processing';
COMMENT ON INDEX idx_organization_metrics_org_type_time IS 'Optimizes metrics dashboard queries';

-- ============================================================================
-- ANALYZE TABLES FOR QUERY OPTIMIZER
-- ============================================================================

-- Update table statistics for better query planning
ANALYZE prospects;
ANALYZE connectors;
ANALYZE prospect_connectors;
ANALYZE team_members;
ANALYZE approval_requests;
ANALYZE email_jobs;
ANALYZE email_metrics;
ANALYZE audit_events;
ANALYZE organization_metrics;
ANALYZE integration_sets;
ANALYZE cookie_jars;
ANALYZE job_idempotency;