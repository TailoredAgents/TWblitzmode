-- Migration to add linkedin_handle column and prevent duplicates

-- 1) Add the column if it doesn't exist
ALTER TABLE prospects
    ADD COLUMN IF NOT EXISTS linkedin_handle TEXT;

-- 2) Backfill from existing linkedin_url
UPDATE prospects
SET linkedin_handle = LOWER(
    REGEXP_REPLACE(
        REGEXP_REPLACE(linkedin_url, '^https?://(www\.)?linkedin\.com/in/', ''), -- strip domain/prefix
        '/+$', ''                                                                 -- strip trailing slashes
    )
)
WHERE linkedin_handle IS NULL
  AND linkedin_url IS NOT NULL;

-- 3) Remove duplicates before creating unique index
-- Keep the first (lowest ID) for each duplicate set
WITH duplicates AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY tenant_id, linkedin_handle ORDER BY id) AS rn
    FROM prospects
    WHERE linkedin_handle IS NOT NULL
)
DELETE FROM prospects
WHERE id IN (
    SELECT id FROM duplicates WHERE rn > 1
);

-- 4) Create unique index to prevent future duplicates
CREATE UNIQUE INDEX IF NOT EXISTS uq_prospects_tenant_handle
    ON prospects (tenant_id, linkedin_handle);

-- 5) Add index for performance
CREATE INDEX IF NOT EXISTS idx_prospects_linkedin_handle
    ON prospects (linkedin_handle);