-- Add sender email settings columns to users table
-- These store user-specific email configuration for outreach

-- Add sender_email column
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_email VARCHAR(255);

-- Add sender_name column
ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_name VARCHAR(255);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_sender_email ON users(sender_email);

-- Add comment for documentation
COMMENT ON COLUMN users.sender_email IS 'User-specific sender email for outreach messages';
COMMENT ON COLUMN users.sender_name IS 'User-specific sender name for outreach messages';