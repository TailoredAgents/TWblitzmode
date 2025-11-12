-- Migration: Add missing columns to dev_sessions table
-- Created: 2025-10-17
-- Description: Add session_id, account_id, tenant_id, device_id, effective_role, permissions, device_fingerprint, idle_expires_at columns

ALTER TABLE dev_sessions
ADD COLUMN IF NOT EXISTS session_id TEXT,
ADD COLUMN IF NOT EXISTS account_id TEXT,
ADD COLUMN IF NOT EXISTS tenant_id TEXT,
ADD COLUMN IF NOT EXISTS device_id INTEGER,
ADD COLUMN IF NOT EXISTS effective_role TEXT,
ADD COLUMN IF NOT EXISTS permissions TEXT,
ADD COLUMN IF NOT EXISTS device_fingerprint TEXT,
ADD COLUMN IF NOT EXISTS idle_expires_at TIMESTAMPTZ;
