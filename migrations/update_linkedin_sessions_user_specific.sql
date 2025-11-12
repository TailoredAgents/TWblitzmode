-- Update linkedin_sessions table to be user-specific instead of just tenant-specific
-- This allows each user to have their own LinkedIn cookies

-- Add user_id column if it doesn't exist
ALTER TABLE linkedin_sessions ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);

-- Create index for user_id lookups
CREATE INDEX IF NOT EXISTS idx_linkedin_sessions_user_id ON linkedin_sessions(user_id);

-- Create composite index for user and tenant lookups
CREATE INDEX IF NOT EXISTS idx_linkedin_sessions_user_tenant ON linkedin_sessions(user_id, tenant_id);

-- Update existing records to set user_id (for migration)
-- This assigns cookies to the first user in each tenant (admin)
UPDATE linkedin_sessions
SET user_id = (
    SELECT MIN(id)
    FROM users
    WHERE users.tenant_id = linkedin_sessions.tenant_id
)
WHERE user_id IS NULL;

-- Add comment for documentation
COMMENT ON COLUMN linkedin_sessions.user_id IS 'User who owns this LinkedIn cookie session';