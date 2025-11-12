-- Fix missing columns in approval_requests table
-- Generated: 2025-09-29
-- Issue: Error escalating requests: column "escalation_reason" does not exist

-- Add missing escalation_reason column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'approval_requests'
        AND column_name = 'escalation_reason'
    ) THEN
        ALTER TABLE approval_requests
        ADD COLUMN escalation_reason TEXT;
    END IF;
END $$;

-- Add escalation_count column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'approval_requests'
        AND column_name = 'escalation_count'
    ) THEN
        ALTER TABLE approval_requests
        ADD COLUMN escalation_count INTEGER DEFAULT 0;
    END IF;
END $$;

-- Add escalated_at column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'approval_requests'
        AND column_name = 'escalated_at'
    ) THEN
        ALTER TABLE approval_requests
        ADD COLUMN escalated_at TIMESTAMP;
    END IF;
END $$;

-- Add escalated_to column if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'approval_requests'
        AND column_name = 'escalated_to'
    ) THEN
        ALTER TABLE approval_requests
        ADD COLUMN escalated_to VARCHAR(255);
    END IF;
END $$;

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_approval_requests_escalation
ON approval_requests(escalated_at, escalation_count)
WHERE escalated_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_approval_requests_status_created
ON approval_requests(status, created_at)
WHERE status IN ('pending', 'escalated');

-- Add comment to document the changes
COMMENT ON COLUMN approval_requests.escalation_reason IS 'Reason for escalation to higher authority';
COMMENT ON COLUMN approval_requests.escalation_count IS 'Number of times this request has been escalated';
COMMENT ON COLUMN approval_requests.escalated_at IS 'Timestamp when request was last escalated';
COMMENT ON COLUMN approval_requests.escalated_to IS 'User/role the request was escalated to';

-- Grant necessary permissions
GRANT SELECT, INSERT, UPDATE ON approval_requests TO vouchlink_ai_user;

-- Verify the changes
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'approval_requests'
AND column_name IN ('escalation_reason', 'escalation_count', 'escalated_at', 'escalated_to')
ORDER BY column_name;