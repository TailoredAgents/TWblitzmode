-- Migration: Add missing columns to dev_mfa_tokens table
-- Created: 2025-10-17
-- Description: Add session_id, account_id, tenant_id, otp_secret, method, delivery_channel columns

ALTER TABLE dev_mfa_tokens
ADD COLUMN IF NOT EXISTS session_id TEXT,
ADD COLUMN IF NOT EXISTS account_id TEXT,
ADD COLUMN IF NOT EXISTS tenant_id TEXT,
ADD COLUMN IF NOT EXISTS otp_secret TEXT,
ADD COLUMN IF NOT EXISTS method TEXT,
ADD COLUMN IF NOT EXISTS delivery_channel TEXT;
