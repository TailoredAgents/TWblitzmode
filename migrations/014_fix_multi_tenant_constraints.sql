-- Fix multi-tenant isolation gaps in corporate schema
-- Ensures connectors and workflow tables enforce organization ownership

BEGIN;

-- Ensure connectors carry organization ownership
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'connectors' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE public.connectors ADD COLUMN organization_id INTEGER;
    END IF;
END;
$$;

-- Backfill connector organization ids from existing relationships
WITH connector_org AS (
    SELECT connector_id, MIN(organization_id) AS organization_id
    FROM prospect_connectors
    GROUP BY connector_id
)
UPDATE connectors c
SET organization_id = co.organization_id
FROM connector_org co
WHERE c.id = co.connector_id AND c.organization_id IS DISTINCT FROM co.organization_id;

-- Fail fast if any connectors remain unowned
DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO orphan_count FROM connectors WHERE organization_id IS NULL;
    IF orphan_count > 0 THEN
        RAISE EXCEPTION 'Found % connectors without organization ownership after backfill', orphan_count;
    END IF;
END;
$$;

ALTER TABLE connectors
    ALTER COLUMN organization_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'unique_org_connector'
    ) THEN
        ALTER TABLE connectors
            ADD CONSTRAINT unique_org_connector UNIQUE (organization_id, linkedin_url);
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'connectors_organization_id_fkey'
    ) THEN
        ALTER TABLE connectors
            ADD CONSTRAINT connectors_organization_id_fkey
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_connectors_org ON connectors(organization_id);

-- Align workflow_contexts tenant/org identifiers
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workflow_contexts_tenant_org_match'
    ) THEN
        ALTER TABLE workflow_contexts
            ADD CONSTRAINT workflow_contexts_tenant_org_match CHECK (tenant_id = organization_id);
    END IF;
END;
$$;

-- Harden approval_requests
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'approval_requests' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE approval_requests ADD COLUMN organization_id INTEGER;
        UPDATE approval_requests SET organization_id = tenant_id WHERE organization_id IS NULL;
    END IF;
END;
$$;

ALTER TABLE approval_requests
    ALTER COLUMN organization_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'approval_requests_organization_id_fkey'
    ) THEN
        ALTER TABLE approval_requests
            ADD CONSTRAINT approval_requests_organization_id_fkey
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'approval_requests_tenant_org_match'
    ) THEN
        ALTER TABLE approval_requests
            ADD CONSTRAINT approval_requests_tenant_org_match CHECK (tenant_id = organization_id);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_approval_requests_org ON approval_requests(organization_id);

-- Harden agent_decisions
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'agent_decisions' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE agent_decisions ADD COLUMN organization_id INTEGER;
        UPDATE agent_decisions SET organization_id = tenant_id WHERE organization_id IS NULL;
    END IF;
END;
$$;

ALTER TABLE agent_decisions
    ALTER COLUMN organization_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_decisions_organization_id_fkey'
    ) THEN
        ALTER TABLE agent_decisions
            ADD CONSTRAINT agent_decisions_organization_id_fkey
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_decisions_tenant_org_match'
    ) THEN
        ALTER TABLE agent_decisions
            ADD CONSTRAINT agent_decisions_tenant_org_match CHECK (tenant_id = organization_id);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_agent_decisions_org ON agent_decisions(organization_id);

-- Harden workflow_templates
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'workflow_templates' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE workflow_templates ADD COLUMN organization_id INTEGER;
        UPDATE workflow_templates SET organization_id = tenant_id WHERE organization_id IS NULL;
    END IF;
END;
$$;

ALTER TABLE workflow_templates
    ALTER COLUMN organization_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workflow_templates_organization_id_fkey'
    ) THEN
        ALTER TABLE workflow_templates
            ADD CONSTRAINT workflow_templates_organization_id_fkey
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workflow_templates_tenant_org_match'
    ) THEN
        ALTER TABLE workflow_templates
            ADD CONSTRAINT workflow_templates_tenant_org_match CHECK (tenant_id = organization_id);
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'unique_org_template_name'
    ) THEN
        ALTER TABLE workflow_templates
            ADD CONSTRAINT unique_org_template_name UNIQUE (organization_id, name);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_workflow_templates_org ON workflow_templates(organization_id);

-- Harden workflow_executions
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'workflow_executions' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE workflow_executions ADD COLUMN organization_id INTEGER;
        UPDATE workflow_executions SET organization_id = tenant_id WHERE organization_id IS NULL;
    END IF;
END;
$$;

ALTER TABLE workflow_executions
    ALTER COLUMN organization_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workflow_executions_organization_id_fkey'
    ) THEN
        ALTER TABLE workflow_executions
            ADD CONSTRAINT workflow_executions_organization_id_fkey
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'workflow_executions_tenant_org_match'
    ) THEN
        ALTER TABLE workflow_executions
            ADD CONSTRAINT workflow_executions_tenant_org_match CHECK (tenant_id = organization_id);
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_workflow_executions_org ON workflow_executions(organization_id);

-- Refresh row-level security policies to enforce organization context
ALTER TABLE connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE connectors FORCE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'connectors' AND polname = 'connectors_org_isolation'
    ) THEN
        DROP POLICY connectors_org_isolation ON connectors;
    END IF;
    CREATE POLICY connectors_org_isolation ON connectors
        USING (organization_id = current_setting('app.current_organization_id', true)::INTEGER);
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'approval_requests' AND polname = 'approval_requests_tenant_isolation'
    ) THEN
        DROP POLICY approval_requests_tenant_isolation ON approval_requests;
    END IF;
    DROP POLICY IF EXISTS approval_requests_org_isolation ON approval_requests;
    CREATE POLICY approval_requests_org_isolation ON approval_requests
        USING (
            organization_id = current_setting('app.current_organization_id', true)::INTEGER
            AND tenant_id = organization_id
        );
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'agent_decisions' AND polname = 'agent_decisions_tenant_isolation'
    ) THEN
        DROP POLICY agent_decisions_tenant_isolation ON agent_decisions;
    END IF;
    DROP POLICY IF EXISTS agent_decisions_org_isolation ON agent_decisions;
    CREATE POLICY agent_decisions_org_isolation ON agent_decisions
        USING (
            organization_id = current_setting('app.current_organization_id', true)::INTEGER
            AND tenant_id = organization_id
        );
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'workflow_templates' AND polname = 'workflow_templates_tenant_isolation'
    ) THEN
        DROP POLICY workflow_templates_tenant_isolation ON workflow_templates;
    END IF;
    DROP POLICY IF EXISTS workflow_templates_org_isolation ON workflow_templates;
    CREATE POLICY workflow_templates_org_isolation ON workflow_templates
        USING (
            organization_id = current_setting('app.current_organization_id', true)::INTEGER
            AND tenant_id = organization_id
        );
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'workflow_executions' AND polname = 'workflow_executions_tenant_isolation'
    ) THEN
        DROP POLICY workflow_executions_tenant_isolation ON workflow_executions;
    END IF;
    DROP POLICY IF EXISTS workflow_executions_org_isolation ON workflow_executions;
    CREATE POLICY workflow_executions_org_isolation ON workflow_executions
        USING (
            organization_id = current_setting('app.current_organization_id', true)::INTEGER
            AND tenant_id = organization_id
        );
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'workflow_node_executions' AND polname = 'workflow_node_executions_tenant_isolation'
    ) THEN
        DROP POLICY workflow_node_executions_tenant_isolation ON workflow_node_executions;
    END IF;
    DROP POLICY IF EXISTS workflow_node_executions_org_isolation ON workflow_node_executions;
    CREATE POLICY workflow_node_executions_org_isolation ON workflow_node_executions
        USING (
            EXISTS (
                SELECT 1
                FROM workflow_executions we
                WHERE we.id = workflow_node_executions.execution_id
                  AND we.organization_id = current_setting('app.current_organization_id', true)::INTEGER
                  AND we.tenant_id = we.organization_id
            )
        );
END;
$$;

COMMIT;