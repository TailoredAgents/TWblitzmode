-- Add is_active column to users table (SQLite compatible)
-- This migration adds user status tracking functionality

-- Add the is_active column with default value of TRUE
-- SQLite doesn't support IF NOT EXISTS for ADD COLUMN
ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- Add an index for performance when querying active users
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);