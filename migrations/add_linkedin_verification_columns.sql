-- Add username and full_name columns to linkedin_sessions table
-- September 2025 - Cookie Verification Enhancement

-- Add username column to store LinkedIn username extracted from profile
ALTER TABLE linkedin_sessions ADD COLUMN IF NOT EXISTS username VARCHAR(255);

-- Add full_name column to store user's display name from LinkedIn profile
ALTER TABLE linkedin_sessions ADD COLUMN IF NOT EXISTS full_name VARCHAR(500);

-- Add index on username for faster lookups
CREATE INDEX IF NOT EXISTS idx_linkedin_sessions_username ON linkedin_sessions(username);

-- Add index on full_name for user searches
CREATE INDEX IF NOT EXISTS idx_linkedin_sessions_full_name ON linkedin_sessions(full_name);

-- Add comments for documentation
COMMENT ON COLUMN linkedin_sessions.username IS 'LinkedIn username extracted from profile URL during cookie verification';
COMMENT ON COLUMN linkedin_sessions.full_name IS 'User display name extracted from LinkedIn profile during verification';

-- Update any existing sessions that don't have usernames to mark them for re-verification
UPDATE linkedin_sessions
SET last_verified_at = NULL
WHERE username IS NULL AND is_active = 1;

COMMIT;