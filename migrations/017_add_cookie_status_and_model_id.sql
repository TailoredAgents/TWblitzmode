-- Migration: Lock model usage + audit model_id and cookie status fields
-- Date: 2025-11-10

-- Add cookie_status to team_members if missing
ALTER TABLE IF EXISTS team_members
    ADD COLUMN IF NOT EXISTS cookie_status VARCHAR(32) DEFAULT 'unknown';

-- Add username/full_name columns to linkedin_sessions exist via prior migrations; sanity indexes are in place.

-- Add model_id to agent_decisions for AI decision provenance
ALTER TABLE IF EXISTS agent_decisions
    ADD COLUMN IF NOT EXISTS model_id VARCHAR(100) DEFAULT 'gpt-4.1';

-- Index for querying by model_id if needed
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_agent_decisions_model_id'
    ) THEN
        CREATE INDEX idx_agent_decisions_model_id ON agent_decisions(model_id);
    END IF;
END $$;

-- Document
COMMENT ON COLUMN agent_decisions.model_id IS 'Model identifier used for the AI decision (e.g., gpt-4.1)';

COMMIT;

