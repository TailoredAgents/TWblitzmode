-- Migration 019: Fix user_preferences schema mismatch
-- Description: Add missing preferences JSONB column and update unique constraint
-- Date: 2025-11-06
-- Issue: Code expects a 'preferences' JSONB column and unique constraint on (tenant_id, user_id)
--        but the table only had individual columns and constraint on (user_id)

-- Add the preferences JSONB column that the application code expects
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}'::jsonb;

-- Drop the old single-column unique constraint
ALTER TABLE user_preferences DROP CONSTRAINT IF EXISTS uq_user_preferences_user;

-- Add composite unique constraint on (tenant_id, user_id) to match ON CONFLICT clause in code
ALTER TABLE user_preferences ADD CONSTRAINT IF NOT EXISTS uq_user_preferences_tenant_user UNIQUE (tenant_id, user_id);

-- Verify the changes
DO $$
BEGIN
    -- Check if preferences column exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'user_preferences' AND column_name = 'preferences'
    ) THEN
        RAISE EXCEPTION 'Migration failed: preferences column was not added';
    END IF;

    -- Check if new unique constraint exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'user_preferences'
        AND constraint_name = 'uq_user_preferences_tenant_user'
        AND constraint_type = 'UNIQUE'
    ) THEN
        RAISE EXCEPTION 'Migration failed: unique constraint was not added';
    END IF;

    RAISE NOTICE 'Migration 019 completed successfully';
END $$;
