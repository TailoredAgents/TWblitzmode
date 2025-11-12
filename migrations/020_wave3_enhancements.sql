-- Wave 3 schema enhancements for Tallwave Link

BEGIN;

-- Prospects: stage, source, confidence, dedupe key
ALTER TABLE IF EXISTS prospects
    ADD COLUMN IF NOT EXISTS stage VARCHAR(50) DEFAULT 'research';

ALTER TABLE IF EXISTS prospects
    ADD COLUMN IF NOT EXISTS source VARCHAR(255) DEFAULT 'agentic';

ALTER TABLE IF EXISTS prospects
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,3) DEFAULT 0.0;

ALTER TABLE IF EXISTS prospects
    ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prospects_dedupe_key
    ON prospects (dedupe_key)
    WHERE dedupe_key IS NOT NULL;

-- Background jobs: dry run + impact preview metadata
ALTER TABLE IF EXISTS portal_background_jobs
    ADD COLUMN IF NOT EXISTS dry_run BOOLEAN DEFAULT FALSE;

ALTER TABLE IF EXISTS portal_background_jobs
    ADD COLUMN IF NOT EXISTS impact_preview JSONB;

-- Connector ranking cache table
CREATE TABLE IF NOT EXISTS connector_ranking_cache (
    id SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    cache_key TEXT NOT NULL DEFAULT 'org-default',
    rankings JSONB DEFAULT '[]'::jsonb,
    impact_preview JSONB,
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    UNIQUE (tenant_id, cache_key)
);

CREATE INDEX IF NOT EXISTS idx_connector_ranking_cache_tenant
    ON connector_ranking_cache (tenant_id);

COMMIT;
