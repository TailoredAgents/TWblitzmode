-- Comprehensive migration to fix production database schema
-- This migration is idempotent and can be run multiple times safely

-- 1) Add linkedin_handle column to prospects table
ALTER TABLE public.prospects
  ADD COLUMN IF NOT EXISTS linkedin_handle TEXT;

-- 2) Add updated_at column if missing
ALTER TABLE public.prospects
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- 3) Backfill linkedin_handle from existing URLs
UPDATE public.prospects
SET linkedin_handle = LOWER(
  REGEXP_REPLACE(
    REGEXP_REPLACE(linkedin_url, '^https?://(www\.)?linkedin\.com/in/', ''),
    '/+$', ''
  )
)
WHERE linkedin_handle IS NULL
  AND linkedin_url IS NOT NULL;

-- 4) Remove duplicates before creating unique index
WITH ranked AS (
  SELECT id,
         ROW_NUMBER() OVER (PARTITION BY tenant_id, linkedin_handle ORDER BY id) AS rn
  FROM public.prospects
  WHERE linkedin_handle IS NOT NULL
)
DELETE FROM public.prospects
WHERE id IN (
  SELECT id FROM ranked WHERE rn > 1
);

-- 5) Create unique index for deduplication
CREATE UNIQUE INDEX IF NOT EXISTS uq_prospects_tenant_handle
  ON public.prospects (tenant_id, linkedin_handle);

-- 6) Create index for performance
CREATE INDEX IF NOT EXISTS idx_prospects_linkedin_handle
  ON public.prospects (linkedin_handle);

-- 7) Create or replace the updated_at trigger function
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;

-- 8) Create trigger for prospects updated_at
DROP TRIGGER IF EXISTS update_prospects_updated_at ON public.prospects;
CREATE TRIGGER update_prospects_updated_at
  BEFORE UPDATE ON public.prospects
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 9) Create job_idempotency table if missing
CREATE TABLE IF NOT EXISTS public.job_idempotency (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  result_data TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  UNIQUE(tenant_id, idempotency_key)
);

-- 10) Add missing columns to job_runs table
ALTER TABLE public.job_runs
  ADD COLUMN IF NOT EXISTS provider TEXT,
  ADD COLUMN IF NOT EXISTS job_type TEXT,
  ADD COLUMN IF NOT EXISTS external_id TEXT,
  ADD COLUMN IF NOT EXISTS prospect_id INTEGER REFERENCES public.prospects(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS error_message TEXT,
  ADD COLUMN IF NOT EXISTS result_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS input_data TEXT,
  ADD COLUMN IF NOT EXISTS webhook_received_at TIMESTAMPTZ;

-- 11) Ensure unique constraint exists for job_idempotency (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'job_idempotency_tenant_id_idempotency_key_key'
    ) THEN
        ALTER TABLE public.job_idempotency 
        ADD CONSTRAINT job_idempotency_tenant_id_idempotency_key_key 
        UNIQUE (tenant_id, idempotency_key);
    END IF;
END $$;

-- 12) Create indexes for job tables
CREATE INDEX IF NOT EXISTS idx_job_idempotency_tenant ON public.job_idempotency(tenant_id);
CREATE INDEX IF NOT EXISTS idx_job_idempotency_key ON public.job_idempotency(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_job_runs_external ON public.job_runs(external_id);
CREATE INDEX IF NOT EXISTS idx_job_runs_prospect ON public.job_runs(prospect_id);

-- 13) Add triggers for job tables
DROP TRIGGER IF EXISTS update_job_idempotency_updated_at ON public.job_idempotency;
CREATE TRIGGER update_job_idempotency_updated_at
  BEFORE UPDATE ON public.job_idempotency
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS update_job_runs_updated_at ON public.job_runs;
CREATE TRIGGER update_job_runs_updated_at
  BEFORE UPDATE ON public.job_runs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 14) Add tenant_id column to users table if missing (admin system fix)
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS tenant_id INTEGER;

-- Create index for users tenant_id
CREATE INDEX IF NOT EXISTS idx_users_tenant ON public.users(tenant_id);

-- 15) Add contact_id column to outreach_queue table
ALTER TABLE public.outreach_queue
  ADD COLUMN IF NOT EXISTS contact_id TEXT;

-- 16) Create daily_quotas table for warm-up quota system
CREATE TABLE IF NOT EXISTS public.daily_quotas (
  id SERIAL PRIMARY KEY,
  tenant_id INTEGER NOT NULL,
  for_date DATE NOT NULL DEFAULT CURRENT_DATE,
  used INTEGER NOT NULL DEFAULT 0,
  daily_limit INTEGER NOT NULL DEFAULT 50,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tenant_id, for_date)
);

-- Create index for daily_quotas
CREATE INDEX IF NOT EXISTS idx_daily_quotas_tenant ON public.daily_quotas(tenant_id);
CREATE INDEX IF NOT EXISTS idx_daily_quotas_date ON public.daily_quotas(for_date);

-- 17) Add trigger for daily_quotas updated_at
DROP TRIGGER IF EXISTS update_daily_quotas_updated_at ON public.daily_quotas;
CREATE TRIGGER update_daily_quotas_updated_at
  BEFORE UPDATE ON public.daily_quotas
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 18) Add missing columns to introductions table
ALTER TABLE public.introductions
  ADD COLUMN IF NOT EXISTS message TEXT,
  ADD COLUMN IF NOT EXISTS linkedin_url TEXT,
  ADD COLUMN IF NOT EXISTS contact_id TEXT;

-- 19) Add missing columns to mutual_connections table  
ALTER TABLE public.mutual_connections
  ADD COLUMN IF NOT EXISTS message TEXT,
  ADD COLUMN IF NOT EXISTS linkedin_url TEXT,
  ADD COLUMN IF NOT EXISTS contact_id TEXT;

-- 20) Create indexes for new columns
CREATE INDEX IF NOT EXISTS idx_introductions_contact_id ON public.introductions(contact_id);
CREATE INDEX IF NOT EXISTS idx_mutual_connections_contact_id ON public.mutual_connections(contact_id);
CREATE INDEX IF NOT EXISTS idx_introductions_linkedin_url ON public.introductions(linkedin_url);
CREATE INDEX IF NOT EXISTS idx_mutual_connections_linkedin_url ON public.mutual_connections(linkedin_url);

-- 21) GPT5's fix: Add missing job_runs columns
ALTER TABLE public.job_runs 
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
  ADD COLUMN IF NOT EXISTS cached_result JSONB;

-- 22) GPT5's fix: Create the exact unique index for ON CONFLICT
CREATE UNIQUE INDEX IF NOT EXISTS uq_job_idempotency_tenant_key
  ON public.job_idempotency (tenant_id, idempotency_key);

-- 23) Add job_runs index for idempotency
CREATE INDEX IF NOT EXISTS job_runs_tenant_idem_idx 
  ON public.job_runs(tenant_id, idempotency_key);

-- 24) Create daily_quotas table for quota system
CREATE TABLE IF NOT EXISTS public.daily_quotas (
  tenant_id INTEGER NOT NULL,
  day DATE NOT NULL,
  used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, day)
);