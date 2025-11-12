-- Fix job_idempotency table with proper unique constraint
CREATE TABLE IF NOT EXISTS public.job_idempotency (
  id          SERIAL PRIMARY KEY,
  tenant_id   INTEGER      NOT NULL,
  idempotency_key TEXT     NOT NULL,  -- renamed from job_key for clarity
  prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
  job_type    TEXT         NOT NULL DEFAULT 'find_introducers',
  status      TEXT         NOT NULL DEFAULT 'pending',
  run_id      TEXT,
  result_data TEXT,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ  DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

-- Drop old unique constraint if it exists
DROP INDEX IF EXISTS uq_job_idempotency_tenant_jobkey;

-- Create the correct unique constraint that matches ON CONFLICT clause
CREATE UNIQUE INDEX IF NOT EXISTS job_idempotency_tenant_id_idempotency_key_key
  ON public.job_idempotency (tenant_id, idempotency_key);

-- Also create the index the app expects
CREATE INDEX IF NOT EXISTS idx_job_idempotency_tenant ON public.job_idempotency(tenant_id);
CREATE INDEX IF NOT EXISTS idx_job_idempotency_key ON public.job_idempotency(idempotency_key);

-- Fix job_runs table to have all required columns
CREATE TABLE IF NOT EXISTS public.job_runs (
  id           SERIAL PRIMARY KEY,
  tenant_id    INTEGER,  -- nullable for now to prevent insert failures
  user_id      INTEGER,
  provider     TEXT,
  job_type     TEXT NOT NULL DEFAULT 'find_introducers',
  status       TEXT NOT NULL DEFAULT 'pending',
  external_id  TEXT,  -- Apify run ID
  prospect_id  INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
  result_count INTEGER DEFAULT 0,
  error_message TEXT,
  input_data   TEXT,
  started_at   TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  webhook_received_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Add missing columns if table already exists
ALTER TABLE public.job_runs
  ADD COLUMN IF NOT EXISTS tenant_id INTEGER,
  ADD COLUMN IF NOT EXISTS user_id INTEGER,
  ADD COLUMN IF NOT EXISTS provider TEXT,
  ADD COLUMN IF NOT EXISTS job_type TEXT DEFAULT 'find_introducers',
  ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS external_id TEXT,
  ADD COLUMN IF NOT EXISTS prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS result_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS error_message TEXT,
  ADD COLUMN IF NOT EXISTS input_data TEXT,
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS webhook_received_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Make tenant_id nullable temporarily to prevent insert failures
ALTER TABLE public.job_runs ALTER COLUMN tenant_id DROP NOT NULL;

-- Create indexes for job_runs
CREATE INDEX IF NOT EXISTS idx_job_runs_tenant ON public.job_runs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_job_runs_external ON public.job_runs(external_id);
CREATE INDEX IF NOT EXISTS idx_job_runs_prospect ON public.job_runs(prospect_id);
CREATE INDEX IF NOT EXISTS idx_job_runs_status ON public.job_runs(status);

-- Create or update trigger function
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add triggers for updated_at
DROP TRIGGER IF EXISTS update_job_idempotency_updated_at ON public.job_idempotency;
CREATE TRIGGER update_job_idempotency_updated_at
  BEFORE UPDATE ON public.job_idempotency
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS update_job_runs_updated_at ON public.job_runs;
CREATE TRIGGER update_job_runs_updated_at
  BEFORE UPDATE ON public.job_runs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();