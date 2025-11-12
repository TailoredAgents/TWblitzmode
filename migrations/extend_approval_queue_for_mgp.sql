-- Migration: Extend existing approval queue for Master Game Plan workflows
-- Master Game Plan Implementation - Approval Queue Integration
-- Date: 2025-09-29

-- Create workflow_contexts table for tracking Master Game Plan workflow state
CREATE TABLE IF NOT EXISTS workflow_contexts (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR(255) UNIQUE NOT NULL,
    organization_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    tenant_id INTEGER,
    workflow_state VARCHAR(50) DEFAULT 'active',
    current_action VARCHAR(100),
    steps_completed INTEGER DEFAULT 0,
    steps_total INTEGER DEFAULT 7,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    context_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create agent_decisions table for audit trail
CREATE TABLE IF NOT EXISTS agent_decisions (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR(255) NOT NULL,
    organization_id INTEGER NOT NULL,
    agent_name VARCHAR(100) NOT NULL,
    decision_type VARCHAR(100),
    reasoning TEXT,
    confidence_score DECIMAL(3,2),
    decision_data JSONB,
    decided_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add Master Game Plan specific columns to existing approval_requests table
DO $$
BEGIN
    -- Add workflow_id column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'approval_requests' AND column_name = 'workflow_id') THEN
        ALTER TABLE approval_requests ADD COLUMN workflow_id VARCHAR(255);
    END IF;

    -- Add risk_score column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'approval_requests' AND column_name = 'risk_score') THEN
        ALTER TABLE approval_requests ADD COLUMN risk_score DECIMAL(3,2) DEFAULT 0.0;
    END IF;

    -- Add priority column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'approval_requests' AND column_name = 'priority') THEN
        ALTER TABLE approval_requests ADD COLUMN priority VARCHAR(20) DEFAULT 'medium';
    END IF;

    -- Add timeout_at column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'approval_requests' AND column_name = 'timeout_at') THEN
        ALTER TABLE approval_requests ADD COLUMN timeout_at TIMESTAMP WITH TIME ZONE;
    END IF;

    -- Add description column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'approval_requests' AND column_name = 'description') THEN
        ALTER TABLE approval_requests ADD COLUMN description TEXT;
    END IF;

    -- Add approval_comments column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'approval_requests' AND column_name = 'approval_comments') THEN
        ALTER TABLE approval_requests ADD COLUMN approval_comments TEXT;
    END IF;

    -- Add rejection_reason column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'approval_requests' AND column_name = 'rejection_reason') THEN
        ALTER TABLE approval_requests ADD COLUMN rejection_reason TEXT;
    END IF;

    -- Add approver_type column if it doesn't exist (to distinguish from approver_id)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'approval_requests' AND column_name = 'approver_type') THEN
        ALTER TABLE approval_requests ADD COLUMN approver_type VARCHAR(50);
    END IF;
END $$;

-- Add Master Game Plan specific columns to existing audit_events table
DO $$
BEGIN
    -- Add tenant_id column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'audit_events' AND column_name = 'tenant_id') THEN
        ALTER TABLE audit_events ADD COLUMN tenant_id INTEGER;
    END IF;

    -- Modify actor_id to support string IDs (for workflows and agents)
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'audit_events' AND column_name = 'actor_id' AND data_type = 'integer') THEN
        -- First, convert existing integer values to strings
        ALTER TABLE audit_events ALTER COLUMN actor_id TYPE VARCHAR(255) USING actor_id::VARCHAR(255);
    END IF;

    -- Modify target_id to support string IDs
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'audit_events' AND column_name = 'target_id' AND data_type = 'integer') THEN
        ALTER TABLE audit_events ALTER COLUMN target_id TYPE VARCHAR(255) USING target_id::VARCHAR(255);
    END IF;
END $$;

-- Add indexes for performance optimization

-- workflow_contexts indexes
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_workflow_id ON workflow_contexts(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_org_state ON workflow_contexts(organization_id, workflow_state);
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_tenant ON workflow_contexts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_updated ON workflow_contexts(updated_at);

-- agent_decisions indexes
CREATE INDEX IF NOT EXISTS idx_agent_decisions_workflow_id ON agent_decisions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_org_agent ON agent_decisions(organization_id, agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_decided_at ON agent_decisions(decided_at);

-- New indexes for approval_requests Master Game Plan fields
CREATE INDEX IF NOT EXISTS idx_approval_requests_workflow_id ON approval_requests(workflow_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_priority ON approval_requests(priority);
CREATE INDEX IF NOT EXISTS idx_approval_requests_timeout ON approval_requests(timeout_at);

-- New indexes for audit_events Master Game Plan fields
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant ON audit_events(tenant_id);

-- Add foreign key constraints
DO $$
BEGIN
    -- Add organization foreign keys if organizations table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'organizations') THEN
        -- workflow_contexts organization constraint
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints
                       WHERE constraint_name = 'fk_workflow_contexts_organization') THEN
            ALTER TABLE workflow_contexts
            ADD CONSTRAINT fk_workflow_contexts_organization
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
        END IF;

        -- agent_decisions organization constraint
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints
                       WHERE constraint_name = 'fk_agent_decisions_organization') THEN
            ALTER TABLE agent_decisions
            ADD CONSTRAINT fk_agent_decisions_organization
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
        END IF;
    END IF;

    -- Add workflow foreign key relationships
    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints
                   WHERE constraint_name = 'fk_approval_requests_workflow') THEN
        ALTER TABLE approval_requests
        ADD CONSTRAINT fk_approval_requests_workflow
        FOREIGN KEY (workflow_id) REFERENCES workflow_contexts(workflow_id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints
                   WHERE constraint_name = 'fk_agent_decisions_workflow') THEN
        ALTER TABLE agent_decisions
        ADD CONSTRAINT fk_agent_decisions_workflow
        FOREIGN KEY (workflow_id) REFERENCES workflow_contexts(workflow_id) ON DELETE CASCADE;
    END IF;
END $$;

-- Add helpful comments
COMMENT ON TABLE workflow_contexts IS 'Tracks the state and progress of Master Game Plan workflows';
COMMENT ON COLUMN workflow_contexts.workflow_id IS 'Unique identifier for the workflow instance';
COMMENT ON COLUMN workflow_contexts.workflow_state IS 'Current state: active, completed, failed, paused';
COMMENT ON COLUMN workflow_contexts.current_action IS 'Current step being executed in the workflow';
COMMENT ON COLUMN workflow_contexts.context_data IS 'JSON data containing workflow context and results';

COMMENT ON TABLE agent_decisions IS 'Audit trail of all agent decisions made during workflow execution';
COMMENT ON COLUMN agent_decisions.confidence_score IS 'AI confidence score from 0.0 to 1.0 for the decision';
COMMENT ON COLUMN agent_decisions.decision_data IS 'JSON data containing detailed decision information';

COMMENT ON COLUMN approval_requests.workflow_id IS 'Links approval to Master Game Plan workflow';
COMMENT ON COLUMN approval_requests.risk_score IS 'Risk assessment score from 0.0 to 1.0';
COMMENT ON COLUMN approval_requests.priority IS 'Priority level: critical, high, medium, low';
COMMENT ON COLUMN approval_requests.timeout_at IS 'When this approval request expires';
COMMENT ON COLUMN approval_requests.description IS 'Human-readable description of what needs approval';
COMMENT ON COLUMN approval_requests.approval_comments IS 'Comments provided by approver';
COMMENT ON COLUMN approval_requests.rejection_reason IS 'Reason for rejection if applicable';

-- Create triggers for updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language plpgsql;

-- Apply the trigger to workflow_contexts
DROP TRIGGER IF EXISTS update_workflow_contexts_updated_at ON workflow_contexts;
CREATE TRIGGER update_workflow_contexts_updated_at
    BEFORE UPDATE ON workflow_contexts
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();

-- Log successful completion
DO $$
BEGIN
    -- Create a simple log entry in audit_events to track this migration
    INSERT INTO audit_events (organization_id, actor_type, actor_id, action, target_type, target_id, payload)
    VALUES (1, 'system', 'migration', 'database_migration', 'schema', 'extend_approval_queue_for_mgp',
            '{"migration": "extend_approval_queue_for_mgp", "status": "completed", "timestamp": "' || NOW()::text || '"}');
EXCEPTION
    WHEN OTHERS THEN
        -- Migration succeeded even if logging failed
        NULL;
END $$;