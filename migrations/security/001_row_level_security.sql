-- Row Level Security Migration
-- Critical security enhancement for multi-tenant isolation
-- Date: September 26, 2025

-- Enable RLS on all multi-tenant tables
DO $$
DECLARE
    target RECORD;
    table_policies CONSTANT JSONB := '[
        {"table": "organizations", "policy": "organizations_tenant_isolation", "column": "id"},
        {"table": "team_members", "policy": "team_members_tenant_isolation", "column": "organization_id"},
        {"table": "prospects", "policy": "prospects_tenant_isolation", "column": "organization_id"},
        {"table": "prospect_connectors", "policy": "prospect_connectors_tenant_isolation", "column": "organization_id"},
        {"table": "job_runs", "policy": "job_runs_tenant_isolation", "column": "organization_id"},
        {"table": "job_idempotency", "policy": "job_idempotency_tenant_isolation", "column": "organization_id"},
        {"table": "email_jobs", "policy": "email_jobs_tenant_isolation", "column": "organization_id"},
        {"table": "linkedin_sessions", "policy": "linkedin_sessions_tenant_isolation", "column": "tenant_id"},
        {"table": "user_integrations", "policy": "user_integrations_tenant_isolation", "column": "tenant_id"},
        {"table": "tenant_settings", "policy": "tenant_settings_isolation", "column": "tenant_id"},
        {"table": "contacts", "policy": "contacts_tenant_isolation", "column": "tenant_id"},
        {"table": "outreach_queue", "policy": "outreach_queue_tenant_isolation", "column": "tenant_id"},
        {"table": "prospect_mutuals", "policy": "prospect_mutuals_tenant_isolation", "column": "tenant_id"}
    ]'::JSONB;
BEGIN
    FOR target IN
        SELECT
            (value ->> 'table') AS table_name,
            (value ->> 'policy') AS policy_name,
            (value ->> 'column') AS tenant_column
        FROM jsonb_array_elements(table_policies)
    LOOP
        IF to_regclass(format('public.%I', target.table_name)) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', target.table_name);
            EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', target.table_name);
            EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', target.policy_name, target.table_name);
            EXECUTE format(
                'CREATE POLICY %I ON public.%I USING (%I = current_setting(''app.current_tenant_id'', true)::INTEGER)',
                target.policy_name,
                target.table_name,
                target.tenant_column
            );
        END IF;
    END LOOP;
END;
$$;

-- Create function to set tenant context for application sessions
CREATE OR REPLACE FUNCTION set_tenant_context(tenant_id INTEGER)
RETURNS void AS $$
BEGIN
    IF tenant_id IS NULL THEN
        RAISE EXCEPTION 'tenant_id cannot be null when setting tenant context';
    END IF;
    PERFORM set_config('app.current_tenant_id', tenant_id::text, true);
END;
$$ LANGUAGE plpgsql;

-- Grant usage to application role
DO $$
BEGIN
    IF to_regrole('vouchlink_app_role') IS NOT NULL THEN
        GRANT EXECUTE ON FUNCTION set_tenant_context(INTEGER) TO vouchlink_app_role;
    END IF;
END;
$$;