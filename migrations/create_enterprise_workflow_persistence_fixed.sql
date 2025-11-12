-- Enterprise Workflow Persistence Schema
-- Event sourcing, saga patterns, and workflow orchestration for Master Game Plan

-- Event Store: Core event sourcing table
CREATE TABLE IF NOT EXISTS event_store (
    id BIGSERIAL PRIMARY KEY,
    stream_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1,
    data JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    correlation_id VARCHAR(255),
    causation_id VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_event_store_stream_id ON event_store(stream_id);
CREATE INDEX IF NOT EXISTS idx_event_store_event_type ON event_store(event_type);
CREATE INDEX IF NOT EXISTS idx_event_store_created_at ON event_store(created_at);
CREATE INDEX IF NOT EXISTS idx_event_store_correlation_id ON event_store(correlation_id);

-- Process Snapshots: Workflow state snapshots for recovery
CREATE TABLE IF NOT EXISTS process_snapshots (
    id SERIAL PRIMARY KEY,
    process_id VARCHAR(255) UNIQUE NOT NULL,
    process_type VARCHAR(100) NOT NULL,
    snapshot_data JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_process_snapshots_process_id ON process_snapshots(process_id);
CREATE INDEX IF NOT EXISTS idx_process_snapshots_process_type ON process_snapshots(process_type);

-- Saga State: Long-running transaction state management
CREATE TABLE IF NOT EXISTS saga_state (
    id SERIAL PRIMARY KEY,
    saga_id VARCHAR(255) UNIQUE NOT NULL,
    saga_type VARCHAR(100) NOT NULL,
    current_step VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    state_data JSONB NOT NULL,
    compensation_data JSONB,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saga_state_saga_id ON saga_state(saga_id);
CREATE INDEX IF NOT EXISTS idx_saga_state_status ON saga_state(status);
CREATE INDEX IF NOT EXISTS idx_saga_state_saga_type ON saga_state(saga_type);

-- Outbox Events: Reliable event publishing pattern
CREATE TABLE IF NOT EXISTS outbox_events (
    id BIGSERIAL PRIMARY KEY,
    event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    aggregate_id VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,
    retry_count INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_events_status ON outbox_events(status);
CREATE INDEX IF NOT EXISTS idx_outbox_events_event_type ON outbox_events(event_type);
CREATE INDEX IF NOT EXISTS idx_outbox_events_created_at ON outbox_events(created_at);

-- Workflow States: Current state of active workflows
CREATE TABLE IF NOT EXISTS workflow_states (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR(255) UNIQUE NOT NULL,
    workflow_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'running',
    current_state JSONB NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    last_heartbeat TIMESTAMP WITH TIME ZONE,
    timeout_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_workflow_states_workflow_id ON workflow_states(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_states_status ON workflow_states(status);
CREATE INDEX IF NOT EXISTS idx_workflow_states_workflow_type ON workflow_states(workflow_type);

-- Workflow Queues: Priority queue for workflow execution
CREATE TABLE IF NOT EXISTS workflow_queues (
    id SERIAL PRIMARY KEY,
    queue_id VARCHAR(255) NOT NULL,
    workflow_id VARCHAR(255) NOT NULL,
    priority INTEGER DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_workflow_queues_queue_id ON workflow_queues(queue_id);
CREATE INDEX IF NOT EXISTS idx_workflow_queues_workflow_id ON workflow_queues(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_queues_status_priority ON workflow_queues(status, priority DESC);

-- Workflow Queue Metadata: Configuration for workflow queues
CREATE TABLE IF NOT EXISTS workflow_queue_metadata (
    id SERIAL PRIMARY KEY,
    queue_id VARCHAR(255) UNIQUE NOT NULL,
    queue_type VARCHAR(100) NOT NULL,
    max_concurrent INTEGER DEFAULT 10,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_queue_metadata_queue_id ON workflow_queue_metadata(queue_id);
CREATE INDEX IF NOT EXISTS idx_workflow_queue_metadata_is_enabled ON workflow_queue_metadata(is_enabled);

-- Views for monitoring
CREATE OR REPLACE VIEW active_workflows AS
SELECT
    workflow_id,
    workflow_type,
    status,
    started_at,
    updated_at,
    last_heartbeat,
    timeout_at
FROM workflow_states
WHERE status NOT IN ('completed', 'failed', 'cancelled');

CREATE OR REPLACE VIEW workflow_queue_summary AS
SELECT
    wq.queue_id,
    wqm.queue_type,
    COUNT(*) as total_workflows,
    COUNT(CASE WHEN wq.status = 'queued' THEN 1 END) as queued_count,
    COUNT(CASE WHEN wq.status = 'processing' THEN 1 END) as processing_count,
    MAX(wq.queued_at) as latest_queued,
    wqm.is_enabled
FROM workflow_queues wq
JOIN workflow_queue_metadata wqm ON wq.queue_id = wqm.queue_id
GROUP BY wq.queue_id, wqm.queue_type, wqm.is_enabled;

-- Comments for documentation
COMMENT ON TABLE event_store IS 'Event sourcing store for all workflow events';
COMMENT ON TABLE process_snapshots IS 'Periodic snapshots of workflow state for fast recovery';
COMMENT ON TABLE saga_state IS 'Manages long-running distributed transactions with compensation';
COMMENT ON TABLE outbox_events IS 'Reliable event publishing pattern for external integrations';
COMMENT ON TABLE workflow_states IS 'Current state of all active workflows';
COMMENT ON TABLE workflow_queues IS 'Priority queue for workflow execution';

COMMENT ON COLUMN event_store.stream_id IS 'Aggregate identifier for event grouping';
COMMENT ON COLUMN event_store.data IS 'Event payload as JSON';
