-- Migration: Create Enterprise Workflow Persistence Schema
-- Complete workflow state management with PostgreSQL persistence
-- Date: 2025-09-30

-- Create workflow_states table for comprehensive workflow management
CREATE TABLE IF NOT EXISTS workflow_states (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR(255) UNIQUE NOT NULL,
    organization_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    workflow_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    current_stage VARCHAR(100),
    progress_percentage DECIMAL(5,2) DEFAULT 0.0,
    priority VARCHAR(20) DEFAULT 'normal',

    -- State management
    is_paused BOOLEAN DEFAULT FALSE,
    pause_reason TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    last_heartbeat TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    timeout_at TIMESTAMP WITH TIME ZONE,

    -- Data storage
    prospects JSONB DEFAULT '[]',
    team_members JSONB DEFAULT '[]',
    results JSONB DEFAULT '{}',
    errors JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}'
);

-- Create workflow_queues table for persistent queue management
CREATE TABLE IF NOT EXISTS workflow_queues (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR(255) NOT NULL,
    queue_id VARCHAR(255) NOT NULL,
    priority VARCHAR(20) DEFAULT 'normal',
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'queued',

    UNIQUE(workflow_id)
);

-- Create workflow_queue_metadata table for queue configuration
CREATE TABLE IF NOT EXISTS workflow_queue_metadata (
    id SERIAL PRIMARY KEY,
    queue_id VARCHAR(255) UNIQUE NOT NULL,
    queue_type VARCHAR(100) NOT NULL,
    max_concurrent INTEGER DEFAULT 10,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create workflow_checkpoints table for state recovery
CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR(255) NOT NULL,
    checkpoint_stage VARCHAR(100) NOT NULL,
    checkpoint_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create event_store table for event-driven architecture
CREATE TABLE IF NOT EXISTS event_store (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(64) UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    source VARCHAR(255) NOT NULL,
    data JSONB NOT NULL,
    priority VARCHAR(20) DEFAULT 'normal',
    correlation_id VARCHAR(64),
    causation_id VARCHAR(64),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1,
    metadata JSONB DEFAULT '{}'
);

-- Performance indexes for workflow_states
CREATE INDEX IF NOT EXISTS idx_workflow_states_workflow_id ON workflow_states(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_org_status ON workflow_states(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_workflow_states_user ON workflow_states(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_type ON workflow_states(workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflow_states_priority ON workflow_states(priority);
CREATE INDEX IF NOT EXISTS idx_workflow_states_created ON workflow_states(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_states_updated ON workflow_states(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_states_heartbeat ON workflow_states(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_workflow_states_timeout ON workflow_states(timeout_at)
    WHERE status NOT IN ('completed', 'failed', 'cancelled');

-- Performance indexes for workflow_queues
CREATE INDEX IF NOT EXISTS idx_workflow_queues_workflow_id ON workflow_queues(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_queues_queue_id ON workflow_queues(queue_id);
CREATE INDEX IF NOT EXISTS idx_workflow_queues_priority ON workflow_queues(priority);
CREATE INDEX IF NOT EXISTS idx_workflow_queues_queued_at ON workflow_queues(queued_at);
CREATE INDEX IF NOT EXISTS idx_workflow_queues_status ON workflow_queues(status);

-- Performance indexes for workflow_queue_metadata
CREATE INDEX IF NOT EXISTS idx_workflow_queue_metadata_queue_id ON workflow_queue_metadata(queue_id);
CREATE INDEX IF NOT EXISTS idx_workflow_queue_metadata_type ON workflow_queue_metadata(queue_type);
CREATE INDEX IF NOT EXISTS idx_workflow_queue_metadata_enabled ON workflow_queue_metadata(is_enabled);

-- Performance indexes for workflow_checkpoints
CREATE INDEX IF NOT EXISTS idx_workflow_checkpoints_workflow ON workflow_checkpoints(workflow_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_checkpoints_stage ON workflow_checkpoints(checkpoint_stage);

-- Performance indexes for event_store
CREATE INDEX IF NOT EXISTS idx_event_store_event_id ON event_store(event_id);
CREATE INDEX IF NOT EXISTS idx_event_store_type_time ON event_store(event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_event_store_correlation ON event_store(correlation_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_event_store_source ON event_store(source, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_event_store_timestamp ON event_store(timestamp DESC);

-- Foreign key constraints (defensive approach)
DO $$
BEGIN
    -- Add organization foreign keys if organizations table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'organizations') THEN
        ALTER TABLE workflow_states
        ADD CONSTRAINT fk_workflow_states_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;

    -- Add user foreign keys if users table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        ALTER TABLE workflow_states
        ADD CONSTRAINT fk_workflow_states_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;

    -- Add workflow foreign key for queues
    ALTER TABLE workflow_queues
    ADD CONSTRAINT fk_workflow_queues_workflow
    FOREIGN KEY (workflow_id) REFERENCES workflow_states(workflow_id) ON DELETE CASCADE;

    -- Add workflow foreign key for checkpoints
    ALTER TABLE workflow_checkpoints
    ADD CONSTRAINT fk_workflow_checkpoints_workflow
    FOREIGN KEY (workflow_id) REFERENCES workflow_states(workflow_id) ON DELETE CASCADE;

EXCEPTION
    WHEN OTHERS THEN
        -- Continue if foreign key constraints fail (tables may not exist yet)
        NULL;
END $$;

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at triggers
DROP TRIGGER IF EXISTS update_workflow_states_updated_at ON workflow_states;
CREATE TRIGGER update_workflow_states_updated_at
    BEFORE UPDATE ON workflow_states
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();

DROP TRIGGER IF EXISTS update_workflow_queue_metadata_updated_at ON workflow_queue_metadata;
CREATE TRIGGER update_workflow_queue_metadata_updated_at
    BEFORE UPDATE ON workflow_queue_metadata
    FOR EACH ROW
    EXECUTE PROCEDURE update_updated_at_column();

-- Create helpful views for workflow monitoring
CREATE OR REPLACE VIEW active_workflows AS
SELECT
    workflow_id,
    organization_id,
    user_id,
    workflow_type,
    status,
    current_stage,
    progress_percentage,
    priority,
    is_paused,
    created_at,
    updated_at,
    last_heartbeat,
    timeout_at
FROM workflow_states
WHERE status NOT IN ('completed', 'failed', 'cancelled');

CREATE OR REPLACE VIEW workflow_queue_summary AS
SELECT
    queue_id,
    queue_type,
    COUNT(*) as total_workflows,
    COUNT(CASE WHEN status = 'queued' THEN 1 END) as queued_count,
    COUNT(CASE WHEN status = 'processing' THEN 1 END) as processing_count,
    MAX(queued_at) as latest_queued,
    wqm.is_enabled
FROM workflow_queues wq
JOIN workflow_queue_metadata wqm ON wq.queue_id = wqm.queue_id
GROUP BY wq.queue_id, wqm.queue_type, wqm.is_enabled;

-- Comments for documentation
COMMENT ON TABLE workflow_states IS 'Complete workflow state management with enterprise persistence';
COMMENT ON COLUMN workflow_states.workflow_id IS 'Unique identifier for the workflow instance';
COMMENT ON COLUMN workflow_states.status IS 'Current status: pending, running, paused, completed, failed, cancelled, recovering, timeout';
COMMENT ON COLUMN workflow_states.current_stage IS 'Current execution stage within the workflow';
COMMENT ON COLUMN workflow_states.progress_percentage IS 'Completion percentage from 0.0 to 100.0';
COMMENT ON COLUMN workflow_states.is_paused IS 'Whether the workflow is currently paused';
COMMENT ON COLUMN workflow_states.last_heartbeat IS 'Last heartbeat timestamp for monitoring';

COMMENT ON TABLE workflow_queues IS 'Persistent workflow queue management for enterprise scaling';
COMMENT ON COLUMN workflow_queues.queue_id IS 'Queue identifier (e.g., mgp_orchestrator_high_priority)';
COMMENT ON COLUMN workflow_queues.priority IS 'Queue priority: low, normal, high, urgent';

COMMENT ON TABLE workflow_queue_metadata IS 'Configuration metadata for workflow queues';
COMMENT ON COLUMN workflow_queue_metadata.max_concurrent IS 'Maximum concurrent workflows for this queue';

COMMENT ON TABLE workflow_checkpoints IS 'Workflow state checkpoints for recovery';
COMMENT ON COLUMN workflow_checkpoints.checkpoint_data IS 'Serialized workflow state at checkpoint';

COMMENT ON TABLE event_store IS 'Event sourcing store for event-driven architecture';
COMMENT ON COLUMN event_store.correlation_id IS 'Correlation ID for tracking related events';
COMMENT ON COLUMN event_store.data IS 'Event payload as JSON';

-- Log the completion of this migration
DO $$
BEGIN
    -- Create migrations table if it doesn't exist
    CREATE TABLE IF NOT EXISTS enterprise_migrations (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) UNIQUE NOT NULL,
        executed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    -- Log this migration
    INSERT INTO enterprise_migrations (name, executed_at)
    VALUES ('create_enterprise_workflow_persistence', NOW())
    ON CONFLICT (name) DO UPDATE SET executed_at = NOW();
END $$;