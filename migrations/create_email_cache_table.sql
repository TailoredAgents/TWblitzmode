-- Migration: Create email cache table for CorporateEmailEnrichmentService
-- Master Game Plan Implementation - Email Enrichment Phase
-- Date: 2025-09-29

-- Create email cache table for caching email enrichment results
CREATE TABLE IF NOT EXISTS email_cache (
    id SERIAL PRIMARY KEY,
    connector_id INTEGER NOT NULL,
    organization_id INTEGER NOT NULL,
    email VARCHAR(255),
    confidence DECIMAL(3,2),
    source VARCHAR(50),
    status VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Ensure unique combination of connector and organization
    CONSTRAINT unique_connector_org UNIQUE(connector_id, organization_id)
);

-- Add indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_email_cache_org ON email_cache(organization_id);
CREATE INDEX IF NOT EXISTS idx_email_cache_created ON email_cache(created_at);
CREATE INDEX IF NOT EXISTS idx_email_cache_status ON email_cache(status);
CREATE INDEX IF NOT EXISTS idx_email_cache_connector ON email_cache(connector_id);

-- Add foreign key constraints (if tables exist)
-- Note: We're being defensive here since this is a migration
DO $$
BEGIN
    -- Add organization foreign key if organizations table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'organizations') THEN
        ALTER TABLE email_cache
        ADD CONSTRAINT fk_email_cache_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
    END IF;

    -- Add connector foreign key if connectors table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'connectors') THEN
        ALTER TABLE email_cache
        ADD CONSTRAINT fk_email_cache_connector
        FOREIGN KEY (connector_id) REFERENCES connectors(id) ON DELETE CASCADE;
    END IF;
END $$;

-- Add helpful comments
COMMENT ON TABLE email_cache IS 'Cache table for email enrichment results to avoid duplicate API calls';
COMMENT ON COLUMN email_cache.connector_id IS 'ID of the connector whose email was enriched';
COMMENT ON COLUMN email_cache.organization_id IS 'Organization that owns this enrichment data';
COMMENT ON COLUMN email_cache.email IS 'The enriched email address (NULL if no email found)';
COMMENT ON COLUMN email_cache.confidence IS 'Confidence score from 0.0 to 1.0 for the email accuracy';
COMMENT ON COLUMN email_cache.source IS 'Source of the email (e.g., cufinder, hunter, manual)';
COMMENT ON COLUMN email_cache.status IS 'Status of the enrichment (e.g., completed, failed, pending)';
COMMENT ON COLUMN email_cache.created_at IS 'When this cache entry was created';

-- Log the completion of this migration
INSERT INTO migration_log (name, executed_at)
VALUES ('create_email_cache_table', NOW())
ON CONFLICT (name) DO UPDATE SET executed_at = NOW();