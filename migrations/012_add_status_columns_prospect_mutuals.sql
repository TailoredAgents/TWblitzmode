-- Add status tracking columns to prospect_mutuals table
-- This fixes the issue where connectors disappear after page refresh
-- by adding proper status tracking that was missing from the original schema

-- Add status column for tracking contacted/new/queued/failed
ALTER TABLE prospect_mutuals 
ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'new' 
CHECK (status IN ('new','queued','contacted','failed'));

-- Add timestamp for last action (contacted, etc.)
ALTER TABLE prospect_mutuals 
ADD COLUMN IF NOT EXISTS last_action_at TIMESTAMP;

-- Add link to introduction record when connector is contacted
ALTER TABLE prospect_mutuals 
ADD COLUMN IF NOT EXISTS introduction_id INTEGER;

-- Add ranking score for sorting connectors
ALTER TABLE prospect_mutuals 
ADD COLUMN IF NOT EXISTS ranking_score FLOAT DEFAULT 0;

-- Add provider column to track which service found the connector
ALTER TABLE prospect_mutuals 
ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'apify';

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_prospect_mutuals_status 
ON prospect_mutuals (status) WHERE status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_prospect_mutuals_prospect_tenant 
ON prospect_mutuals (prospect_id, tenant_id);

CREATE INDEX IF NOT EXISTS idx_prospect_mutuals_ranking 
ON prospect_mutuals (ranking_score DESC) WHERE ranking_score IS NOT NULL;