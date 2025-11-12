-- Migration: Add CUFinder cache table for result caching (PostgreSQL)
-- Reduces API costs by caching enrichment results for 30 days

-- Create CUFinder cache table
CREATE TABLE IF NOT EXISTS cufinder_cache (
    id SERIAL PRIMARY KEY,
    cache_key VARCHAR(255) NOT NULL,
    tenant_id INTEGER NOT NULL,
    email VARCHAR(255),
    confidence DECIMAL(3,2) DEFAULT 0.0,
    status VARCHAR(50) NOT NULL,
    company_domain VARCHAR(255),
    role VARCHAR(255),
    seniority VARCHAR(100),
    department VARCHAR(100),
    cached_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create unique index on cache_key and tenant_id for fast lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_cufinder_cache_key_tenant 
ON cufinder_cache(cache_key, tenant_id);

-- Create index on expiration for cleanup queries
CREATE INDEX IF NOT EXISTS idx_cufinder_cache_expires 
ON cufinder_cache(expires_at);

-- Create index on tenant_id for tenant-scoped queries
CREATE INDEX IF NOT EXISTS idx_cufinder_cache_tenant 
ON cufinder_cache(tenant_id);

-- Add foreign key constraint to ensure tenant exists
-- ALTER TABLE cufinder_cache 
-- ADD CONSTRAINT fk_cufinder_cache_tenant 
-- FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;

-- Add comment explaining the table purpose
COMMENT ON TABLE cufinder_cache IS 'Caches CUFinder email enrichment results to reduce API costs and improve performance';
COMMENT ON COLUMN cufinder_cache.cache_key IS 'Hashed key based on enrichment input data';
COMMENT ON COLUMN cufinder_cache.confidence IS 'CUFinder confidence score (0.00-1.00)';
COMMENT ON COLUMN cufinder_cache.expires_at IS 'Cache expiration timestamp (30 days from creation)';