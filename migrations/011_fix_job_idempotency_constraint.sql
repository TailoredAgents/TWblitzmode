-- Migration 011: Fix job_idempotency unique constraint for ON CONFLICT
-- Addresses the "no unique or exclusion constraint matching the ON CONFLICT specification" error

-- First, check if the constraint already exists
DO $$
BEGIN
    -- Add unique constraint if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'job_idempotency_tenant_id_idempotency_key_key'
    ) THEN
        ALTER TABLE job_idempotency 
        ADD CONSTRAINT job_idempotency_tenant_id_idempotency_key_key 
        UNIQUE (tenant_id, idempotency_key);
        
        RAISE NOTICE 'Added unique constraint job_idempotency_tenant_id_idempotency_key_key';
    ELSE
        RAISE NOTICE 'Constraint job_idempotency_tenant_id_idempotency_key_key already exists';
    END IF;
END $$;

-- Also create an index for performance if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_job_idempotency_tenant_key 
ON job_idempotency (tenant_id, idempotency_key);

-- Add index for job status queries
CREATE INDEX IF NOT EXISTS idx_job_idempotency_status 
ON job_idempotency (status, created_at);