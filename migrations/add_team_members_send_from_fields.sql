-- Migration: Add send_from fields to team_members table
-- Master Game Plan Implementation - Team Member Setup Phase
-- Date: 2025-01-18

-- Add send_from_name and send_from_email columns to existing team_members table
-- These fields store the display name and email used for sending introduction emails

ALTER TABLE team_members
  ADD COLUMN send_from_name TEXT,
  ADD COLUMN send_from_email TEXT;

-- Add index for efficient querying by send_from_email
CREATE INDEX IF NOT EXISTS idx_team_members_send_from_email ON team_members(send_from_email);

-- Update existing records to have default send-from values
-- This ensures backward compatibility for existing team members
UPDATE team_members
SET
  send_from_name = name,
  send_from_email = email
WHERE send_from_name IS NULL OR send_from_email IS NULL;

-- Add constraint to ensure send_from_email is valid when provided
-- Note: PostgreSQL check constraints for email validation
ALTER TABLE team_members
  ADD CONSTRAINT check_send_from_email_format
  CHECK (send_from_email IS NULL OR send_from_email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$');

-- Add comment explaining the purpose of these fields
COMMENT ON COLUMN team_members.send_from_name IS 'Display name used when sending introduction emails on behalf of this team member';
COMMENT ON COLUMN team_members.send_from_email IS 'Email address used as sender when sending introduction emails on behalf of this team member';