-- Migration: Create approval queue tables for Master Game Plan workflow
-- Master Game Plan Implementation - Approval Queue Phase
-- Date: 2025-09-29

-- Create workflow_contexts table for tracking workflow state
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

-- Create approval_requests table for human approval workflows
CREATE TABLE IF NOT EXISTS approval_requests (
    id SERIAL PRIMARY KEY,
    approval_id VARCHAR(255) UNIQUE NOT NULL,
    workflow_id VARCHAR(255) NOT NULL,
    tenant_id INTEGER,
    organization_id INTEGER NOT NULL,
    action VARCHAR(100) NOT NULL,
    description TEXT,
    risk_score DECIMAL(3,2) DEFAULT 0.0,
    context JSONB,
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(20) DEFAULT 'pending',
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    timeout_at TIMESTAMP WITH TIME ZONE,
    responded_at TIMESTAMP WITH TIME ZONE,
    approver_id VARCHAR(255),
    approval_comments TEXT,
    rejection_reason TEXT
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

-- Create audit_events table for comprehensive audit logging
CREATE TABLE IF NOT EXISTS audit_events (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER,
    organization_id INTEGER,
    actor_type VARCHAR(50),
    actor_id VARCHAR(255),
    action VARCHAR(100),
    target_type VARCHAR(50),
    target_id VARCHAR(255),
    payload JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add indexes for performance optimization

-- workflow_contexts indexes
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_workflow_id ON workflow_contexts(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_org_state ON workflow_contexts(organization_id, workflow_state);
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_tenant ON workflow_contexts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_workflow_contexts_updated ON workflow_contexts(updated_at);

-- approval_requests indexes
CREATE INDEX IF NOT EXISTS idx_approval_requests_approval_id ON approval_requests(approval_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_workflow_id ON approval_requests(workflow_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_tenant_status ON approval_requests(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_approval_requests_org_status ON approval_requests(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_approval_requests_priority ON approval_requests(priority);
CREATE INDEX IF NOT EXISTS idx_approval_requests_requested_at ON approval_requests(requested_at);

-- agent_decisions indexes
CREATE INDEX IF NOT EXISTS idx_agent_decisions_workflow_id ON agent_decisions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_org_agent ON agent_decisions(organization_id, agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_decided_at ON agent_decisions(decided_at);

-- audit_events indexes
CREATE INDEX IF NOT EXISTS idx_audit_events_tenant ON audit_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_org_action ON audit_events(organization_id, action);
CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events(actor_type, actor_id);

-- Add foreign key constraints (defensive approach)
DO $$
BEGIN
    -- Add organization foreign keys if organizations table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'organizations') THEN
        ALTER TABLE workflow_contexts
        ADD CONSTRAINT fk_workflow_contexts_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;

        ALTER TABLE approval_requests
        ADD CONSTRAINT fk_approval_requests_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;

        ALTER TABLE agent_decisions
        ADD CONSTRAINT fk_agent_decisions_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;

        ALTER TABLE audit_events
        ADD CONSTRAINT fk_audit_events_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;

    -- Add workflow foreign key relationship
    ALTER TABLE approval_requests
    ADD CONSTRAINT fk_approval_requests_workflow
    FOREIGN KEY (workflow_id) REFERENCES workflow_contexts(workflow_id) ON DELETE CASCADE;

    ALTER TABLE agent_decisions
    ADD CONSTRAINT fk_agent_decisions_workflow
    FOREIGN KEY (workflow_id) REFERENCES workflow_contexts(workflow_id) ON DELETE CASCADE;
END $$;

-- Add helpful comments
COMMENT ON TABLE workflow_contexts IS 'Tracks the state and progress of Master Game Plan workflows';
COMMENT ON COLUMN workflow_contexts.workflow_id IS 'Unique identifier for the workflow instance';
COMMENT ON COLUMN workflow_contexts.workflow_state IS 'Current state: active, completed, failed, paused';
COMMENT ON COLUMN workflow_contexts.current_action IS 'Current step being executed in the workflow';
COMMENT ON COLUMN workflow_contexts.context_data IS 'JSON data containing workflow context and results';

COMMENT ON TABLE approval_requests IS 'Human approval requests for workflow decision points';
COMMENT ON COLUMN approval_requests.approval_id IS 'Unique identifier for the approval request';
COMMENT ON COLUMN approval_requests.risk_score IS 'Risk assessment score from 0.0 to 1.0';
COMMENT ON COLUMN approval_requests.priority IS 'Priority level: critical, high, medium, low';
COMMENT ON COLUMN approval_requests.status IS 'Approval status: pending, approved, rejected, timeout';

COMMENT ON TABLE agent_decisions IS 'Audit trail of all agent decisions made during workflow execution';
COMMENT ON COLUMN agent_decisions.confidence_score IS 'AI confidence score from 0.0 to 1.0 for the decision';
COMMENT ON COLUMN agent_decisions.decision_data IS 'JSON data containing detailed decision information';

COMMENT ON TABLE audit_events IS 'Comprehensive audit log for all system actions and decisions';
COMMENT ON COLUMN audit_events.actor_type IS 'Type of actor: user, system, agent';
COMMENT ON COLUMN audit_events.payload IS 'JSON data containing event details and metadata';

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

-- Log the completion of this migration
INSERT INTO approval_queue_migrations (name, executed_at)
VALUES ('create_approval_queue_tables', NOW())
ON CONFLICT (name) DO UPDATE SET executed_at = NOW();