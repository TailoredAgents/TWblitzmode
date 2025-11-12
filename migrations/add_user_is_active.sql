-- Add is_active column to users table
-- This migration adds user status tracking functionality

-- Add the is_active column with default value of TRUE
-- This ensures existing users remain active by default
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- Update any existing users to be active (redundant but explicit)
UPDATE users SET is_active = TRUE WHERE is_active IS NULL;

-- Add an index for performance when querying active users
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- Comment for future reference
COMMENT ON COLUMN users.is_active IS 'Whether the user account is active/enabled. FALSE means account is disabled.';