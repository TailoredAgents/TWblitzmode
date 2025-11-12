-- Migration: Add agent_events table for Communication Hub enhancements
-- September 2025 - Communication Hub with Actionable Suggestions and Real-time WebSocket Updates

-- Create agent_events table
CREATE TABLE IF NOT EXISTS agent_events (
    id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    session_id UUID,
    event_type VARCHAR(50) NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    level VARCHAR(20) NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    suggestion TEXT, -- Actionable suggestion for users
    tenant_id VARCHAR(50),
    user_id VARCHAR(50),
    workflow_id UUID,
    task_id UUID,
    metadata JSONB DEFAULT '{}',
    organization_id INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_agent_events_agent_id ON agent_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_event_type ON agent_events(event_type);
CREATE INDEX IF NOT EXISTS idx_agent_events_organization_id ON agent_events(organization_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_created_at ON agent_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_level ON agent_events(level);
CREATE INDEX IF NOT EXISTS idx_agent_events_event_id ON agent_events(event_id);

-- Create updated_at trigger function if it doesn't exist
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger for updated_at
DROP TRIGGER IF EXISTS update_agent_events_updated_at ON agent_events;
CREATE TRIGGER update_agent_events_updated_at
    BEFORE UPDATE ON agent_events
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Insert some sample events for testing
INSERT INTO agent_events (
    event_type, agent_id, level, message, suggestion,
    organization_id, metadata
) VALUES
(
    'agent_error',
    'linkedin_scraper_001',
    'error',
    'LinkedIn authentication failed - cookies may be expired',
    'Update LinkedIn cookies in Settings → Integrations → LinkedIn',
    1,
    '{"error_code": "AUTH_FAILED", "service": "linkedin", "retry_count": 3}'
),
(
    'api_error',
    'openai_agent_001',
    'warning',
    'OpenAI API rate limit approaching - 90% of quota used',
    'Monitor API usage in Settings → API Keys → OpenAI Usage',
    1,
    '{"quota_used": 0.9, "quota_remaining": 0.1, "reset_time": "2025-09-30T00:00:00Z"}'
),
(
    'task_complete',
    'prospect_analyzer_001',
    'info',
    'Successfully analyzed 15 prospects from TechCorp batch',
    null,
    1,
    '{"prospects_processed": 15, "batch_id": "batch_001", "success_rate": 1.0}'
),
(
    'system_event',
    'email_service_001',
    'error',
    'SendGrid API configuration error - invalid API key',
    'Verify SendGrid API key in Settings → Email → SendGrid Configuration',
    1,
    '{"api_endpoint": "/v3/mail/send", "error": "Unauthorized", "status_code": 401}'
);

COMMENT ON TABLE agent_events IS 'Stores AI agent events with actionable suggestions for Communication Hub';
COMMENT ON COLUMN agent_events.suggestion IS 'Actionable suggestion to help users resolve issues';
COMMENT ON COLUMN agent_events.metadata IS 'JSON metadata with additional context about the event';
COMMENT ON COLUMN agent_events.level IS 'Event severity: debug, info, warning, error, critical';