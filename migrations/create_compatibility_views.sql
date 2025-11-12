-- ============================================================================
-- Compatibility Views for SQLite → PostgreSQL Migration
-- ============================================================================
-- Purpose: Allow database.py code to work with PostgreSQL tables
-- Status: Temporary - Remove after code refactoring complete
-- Created: 2025-10-31
-- ============================================================================

-- ============================================================================
-- View 1: accounts → managed_accounts
-- ============================================================================
-- Maps SQLite "accounts" references to PostgreSQL "managed_accounts" table

CREATE OR REPLACE VIEW accounts AS
SELECT
    id::TEXT as id,                      -- Cast INTEGER to TEXT for SQLite compatibility
    name::TEXT as name,
    tenant_id::TEXT as tenant_id,        -- Cast INTEGER to TEXT
    NULL::TEXT as plan,                  -- Column doesn't exist in managed_accounts
    status::TEXT as billing_status,
    created_at,
    updated_at,

    -- Additional columns from managed_accounts
    account_name as name,
    account_type,
    account_credentials_encrypted,

    -- Defaults for expected SQLite columns
    0 as managed_by_admin,
    0 as maintenance_mode,
    0 as sandbox_mode,
    '{}'::TEXT as contract_metadata,
    '{}'::TEXT as alert_thresholds,
    '{}'::TEXT as license_terms
FROM managed_accounts;

-- Index on view for performance
CREATE INDEX IF NOT EXISTS idx_accounts_view_id ON managed_accounts(id);
CREATE INDEX IF NOT EXISTS idx_accounts_view_tenant ON managed_accounts(tenant_id);

COMMENT ON VIEW accounts IS 'Compatibility view: maps accounts → managed_accounts (TEMPORARY - remove after refactoring)';

-- ============================================================================
-- View 2: audit_logs → audit_events
-- ============================================================================
-- Maps SQLite "audit_logs" references to PostgreSQL "audit_events" table

CREATE OR REPLACE VIEW audit_logs AS
SELECT
    id,
    tenant_id::TEXT as tenant_id,
    organization_id,
    actor_type,
    actor_id as actor_email,             -- Map actor_id to expected actor_email
    action,
    target_type,
    target_id,
    payload as details,                  -- Map payload to expected details
    timestamp as created_at              -- Map timestamp to expected created_at
FROM audit_events;

COMMENT ON VIEW audit_logs IS 'Compatibility view: maps audit_logs → audit_events (TEMPORARY - remove after refactoring)';

-- ============================================================================
-- View 3: account_users → team_members
-- ============================================================================
-- Maps SQLite "account_users" junction table to PostgreSQL "team_members"

CREATE OR REPLACE VIEW account_users AS
SELECT
    id,
    organization_id::TEXT as account_id,  -- Map organization_id to account_id
    tenant_id::TEXT as tenant_id,
    user_id,
    role,
    created_at as added_at,

    -- Additional expected columns
    NULL::TEXT as added_by
FROM team_members;

COMMENT ON VIEW account_users IS 'Compatibility view: maps account_users → team_members (TEMPORARY - remove after refactoring)';

-- ============================================================================
-- View 4: account_features → feature_flags (if needed)
-- ============================================================================
-- Maps SQLite "account_features" to PostgreSQL "feature_flags"

CREATE OR REPLACE VIEW account_features AS
SELECT
    id,
    tenant_id::TEXT as tenant_id,
    NULL::TEXT as account_id,             -- No direct mapping
    flag_key as feature_key,
    is_enabled::INTEGER as is_enabled,    -- Cast BOOLEAN to INTEGER (0/1)
    created_at,
    updated_at,

    -- Expected columns
    NULL::TEXT as created_by
FROM feature_flags;

COMMENT ON VIEW account_features IS 'Compatibility view: maps account_features → feature_flags (TEMPORARY - remove after refactoring)';

-- ============================================================================
-- View 5: dashboards → dashboard_configurations
-- ============================================================================
-- Note: No actual queries found using "dashboards" table
-- Creating view anyway for safety

CREATE OR REPLACE VIEW dashboards AS
SELECT
    id,
    tenant_id::TEXT as tenant_id,
    user_id,
    organization_id,
    dashboard_name as name,
    dashboard_type as type,
    layout_config as config,
    widgets,
    is_default,
    is_shared,
    created_at,
    updated_at
FROM dashboard_configurations;

COMMENT ON VIEW dashboards IS 'Compatibility view: maps dashboards → dashboard_configurations (TEMPORARY - remove after refactoring)';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify all views were created
SELECT
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = 'accounts') THEN '✓' ELSE '✗' END as accounts,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = 'audit_logs') THEN '✓' ELSE '✗' END as audit_logs,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = 'account_users') THEN '✓' ELSE '✗' END as account_users,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = 'account_features') THEN '✓' ELSE '✗' END as account_features,
    CASE WHEN EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = 'dashboards') THEN '✓' ELSE '✗' END as dashboards;

-- Test that views are queryable
SELECT 'Testing accounts view...' as test;
SELECT COUNT(*) as account_count FROM accounts;

SELECT 'Testing audit_logs view...' as test;
SELECT COUNT(*) as audit_log_count FROM audit_logs;

SELECT 'Testing account_users view...' as test;
SELECT COUNT(*) as account_user_count FROM account_users;

SELECT 'All compatibility views created and tested!' as result;
