-- Migration: Create email_cache table
-- Purpose: Cache email enrichment results to avoid repeated API calls

-- Create email_cache table
CREATE TABLE IF NOT EXISTS email_cache (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    linkedin_url VARCHAR(500) NOT NULL,
    full_name VARCHAR(255),
    company_name VARCHAR(255),
    company_domain VARCHAR(255),
    email VARCHAR(255),
    confidence DECIMAL(3,2) DEFAULT 0.0,
    source VARCHAR(100),
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    CONSTRAINT uk_email_cache_tenant_linkedin UNIQUE (tenant_id, linkedin_url)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_email_cache_tenant_id ON email_cache(tenant_id);
CREATE INDEX IF NOT EXISTS idx_email_cache_linkedin_url ON email_cache(linkedin_url);
CREATE INDEX IF NOT EXISTS idx_email_cache_expires_at ON email_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_email_cache_status ON email_cache(status);

-- Add trigger for updating updated_at
CREATE OR REPLACE FUNCTION update_email_cache_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_email_cache_updated_at ON email_cache;
CREATE TRIGGER trigger_email_cache_updated_at
    BEFORE UPDATE ON email_cache
    FOR EACH ROW
    EXECUTE FUNCTION update_email_cache_updated_at();

-- Comments for documentation
COMMENT ON TABLE email_cache IS 'Caches email enrichment results to avoid repeated API calls and reduce costs';
COMMENT ON COLUMN email_cache.tenant_id IS 'ID of the tenant this cache entry belongs to';
COMMENT ON COLUMN email_cache.linkedin_url IS 'LinkedIn URL used as the lookup key';
COMMENT ON COLUMN email_cache.email IS 'The enriched email address';
COMMENT ON COLUMN email_cache.confidence IS 'Confidence score from 0.0 to 1.0 for the email accuracy';
COMMENT ON COLUMN email_cache.source IS 'Source of the email (e.g., cufinder, manual)';
COMMENT ON COLUMN email_cache.status IS 'Status of the enrichment (e.g., completed, failed, pending)';
COMMENT ON COLUMN email_cache.created_at IS 'When this cache entry was created';
