"""
Database migration runner that ensures all required tables and columns exist
"""
import logging

logger = logging.getLogger(__name__)

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRESQL_AVAILABLE = True
except ImportError:
    logger.warning("psycopg2 not available - PostgreSQL migrations will be skipped")
    POSTGRESQL_AVAILABLE = False

def run_all_migrations(database_url: str):
    """Run all database migrations to ensure schema is up to date"""
    
    if not database_url or not database_url.startswith(('postgresql://', 'postgres://')):
        logger.info("Skipping PostgreSQL migrations - not using PostgreSQL")
        return
    
    if not POSTGRESQL_AVAILABLE:
        logger.warning("PostgreSQL migrations skipped - psycopg2 not available")
        return
    
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        logger.info("Running database migrations...")

        # PHASE 1: CREATE ALL TABLES FIRST (before any ALTER TABLE operations)

        # 1. Create trigger function (needed by all tables with updated_at)
        try:
            cursor.execute("""
                CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    NEW.updated_at := NOW();
                    RETURN NEW;
                END;
                $$
            """)
            logger.info("✓ Updated_at trigger function ensured")
        except Exception as e:
            logger.warning(f"Trigger function warning: {e}")

        # 2. Create tenant_settings table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.tenant_settings (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    setting_key TEXT NOT NULL,
                    setting_value TEXT,
                    encrypted INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (tenant_id, setting_key)
                )
            """)
            logger.info("✓ tenant_settings table ensured")
        except Exception as e:
            logger.warning(f"tenant_settings table warning: {e}")

        # 3. Create job_idempotency table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.job_idempotency (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    prospect_id INTEGER,
                    job_type TEXT NOT NULL DEFAULT 'find_introducers',
                    status TEXT NOT NULL DEFAULT 'pending',
                    run_id TEXT,
                    result_data TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS job_idempotency_tenant_id_idempotency_key_key
                ON public.job_idempotency (tenant_id, idempotency_key)
            """)

            logger.info("✓ job_idempotency table and constraints ensured")
        except Exception as e:
            logger.warning(f"job_idempotency table warning: {e}")

        # 4. Create job_runs table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.job_runs (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER,
                    user_id INTEGER,
                    job_type TEXT DEFAULT 'find_introducers',
                    status TEXT DEFAULT 'pending',
                    external_id TEXT,
                    prospect_id INTEGER,
                    result_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    input_data TEXT,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    webhook_received_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    provider TEXT,
                    cache_expires_at TIMESTAMPTZ,
                    idempotency_key TEXT
                )
            """)
            logger.info("✓ job_runs table ensured")
        except Exception as e:
            logger.warning(f"job_runs table warning: {e}")

        # 5. Create provider_health table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.provider_health (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER,
                    provider TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    error_count INTEGER DEFAULT 1,
                    cooldown_until TIMESTAMPTZ,
                    last_error_at TIMESTAMPTZ DEFAULT NOW(),
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_provider_health_tenant
                ON public.provider_health (tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_provider_health_provider
                ON public.provider_health (provider)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_provider_health_error_type
                ON public.provider_health (error_type)
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_health_tenant_provider_type
                ON public.provider_health (tenant_id, provider, error_type)
            """)

            logger.info("✓ provider_health table and indexes ensured")
        except Exception as e:
            logger.warning(f"provider_health table warning: {e}")

        # 6. Create outreach_queue table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.outreach_queue (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER,
                    prospect_id INTEGER,
                    prospect_name TEXT,
                    prospect_linkedin TEXT,
                    contact_id INTEGER,
                    connector_name TEXT,
                    connector_linkedin TEXT,
                    linkedin_url TEXT,
                    channel TEXT DEFAULT 'linkedin_dm',
                    message TEXT,
                    provider TEXT DEFAULT 'phantombuster',
                    status TEXT DEFAULT 'pending_approval',
                    approved_at TIMESTAMPTZ,
                    sent_at TIMESTAMPTZ,
                    container_id TEXT,
                    run_id TEXT,
                    external_id TEXT,
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_outreach_queue_tenant_id
                ON public.outreach_queue (tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_outreach_queue_status
                ON public.outreach_queue (status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_outreach_queue_prospect_id
                ON public.outreach_queue (prospect_id)
            """)

            logger.info("✓ outreach_queue table structure and indexes ensured")
        except Exception as e:
            logger.warning(f"outreach_queue table warning: {e}")

        # 6b. Create auth_sessions table for refresh-token based session management
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.auth_sessions (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    refresh_token_hash TEXT NOT NULL,
                    token_version INTEGER NOT NULL DEFAULT 1,
                    current_jti TEXT,
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ,
                    last_rotated_at TIMESTAMPTZ DEFAULT NOW(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (tenant_id, session_id)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_tenant
                ON public.auth_sessions (tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
                ON public.auth_sessions (user_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_session
                ON public.auth_sessions (session_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires
                ON public.auth_sessions (expires_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_revoked
                ON public.auth_sessions (revoked_at)
            """)
            cursor.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = 'auth_sessions'
                          AND column_name = 'last_rotated_at'
                    ) THEN
                        ALTER TABLE public.auth_sessions
                        ADD COLUMN last_rotated_at TIMESTAMPTZ DEFAULT NOW();
                    END IF;
                END $$;
            """)
            cursor.execute("ALTER TABLE public.auth_sessions DISABLE ROW LEVEL SECURITY;")
            logger.info("✓ auth_sessions table ensured")
        except Exception as e:
            logger.warning(f"auth_sessions table warning: {e}")

        # 7. Create daily_quotas table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.daily_quotas (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    daily_limit INTEGER NOT NULL DEFAULT 25,
                    items_processed INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (tenant_id, date)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_daily_quotas_tenant_date
                ON public.daily_quotas (tenant_id, date)
            """)

            logger.info("✓ daily_quotas table and indexes ensured")
        except Exception as e:
            logger.warning(f"daily_quotas table warning: {e}")

        # 8. Create prospects table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.prospects (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL DEFAULT 1,
                    full_name TEXT,
                    linkedin_url TEXT NOT NULL,
                    linkedin_handle TEXT,
                    linkedin_aco_id TEXT,
                    company TEXT,
                    headline TEXT,
                    last_checked_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_prospects_url
                ON public.prospects (linkedin_url)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_prospects_tenant_id
                ON public.prospects (tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_prospects_linkedin_handle
                ON public.prospects (linkedin_handle)
            """)

            logger.info("✓ prospects table and indexes ensured")
        except Exception as e:
            logger.warning(f"prospects table warning: {e}")

        # 9. Create contacts table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.contacts (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL DEFAULT 1,
                    full_name TEXT NOT NULL,
                    linkedin_url TEXT,
                    linkedin_urn TEXT,
                    headline TEXT,
                    company TEXT,
                    email TEXT,
                    last_messaged_at TIMESTAMPTZ,
                    strength_score REAL DEFAULT 0,
                    tags TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_contacts_url
                ON public.contacts (linkedin_url)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_contacts_name
                ON public.contacts (full_name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_contacts_company
                ON public.contacts (company)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_contacts_tenant_id
                ON public.contacts (tenant_id)
            """)

            logger.info("✓ contacts table and indexes ensured")
        except Exception as e:
            logger.warning(f"contacts table warning: {e}")

        # 10. Create prospect_mutuals table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.prospect_mutuals (
                    id SERIAL PRIMARY KEY,
                    prospect_id INTEGER NOT NULL,
                    tenant_id INTEGER NOT NULL DEFAULT 1,
                    mutual_full_name TEXT,
                    mutual_linkedin_url TEXT,
                    mutual_headline TEXT,
                    mutual_company TEXT,
                    network_distance TEXT,
                    scraped_via TEXT,
                    scraped_at TIMESTAMPTZ NOT NULL,
                    run_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_mutuals_prospect
                ON public.prospect_mutuals (prospect_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_mutuals_url
                ON public.prospect_mutuals (mutual_linkedin_url)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_mutuals_tenant_id
                ON public.prospect_mutuals (tenant_id)
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_prospect_mutuals_tenant_prospect_url
                ON public.prospect_mutuals (tenant_id, prospect_id, mutual_linkedin_url)
            """)

            logger.info("✓ prospect_mutuals table and indexes ensured")
        except Exception as e:
            logger.warning(f"prospect_mutuals table warning: {e}")

        # 11. Create users table
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.users (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL DEFAULT 1,
                    email VARCHAR(255) NOT NULL,
                    password_hash TEXT,
                    first_name VARCHAR(100),
                    last_name VARCHAR(100),
                    role VARCHAR(50) DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    accepted_terms_at TIMESTAMPTZ,
                    last_login_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_tenant_id
                ON public.users (tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_users_email
                ON public.users (LOWER(email))
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_email
                ON public.users (tenant_id, LOWER(email))
            """)

            logger.info("✓ users table and indexes ensured")
        except Exception as e:
            logger.warning(f"users table warning: {e}")

        # 12. Create cufinder_cache table (inline from migration file)
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.cufinder_cache (
                    id SERIAL PRIMARY KEY,
                    cache_key VARCHAR(255) NOT NULL,
                    tenant_id INTEGER NOT NULL,
                    email VARCHAR(255),
                    confidence DECIMAL(3,2) DEFAULT 0.0,
                    status VARCHAR(50) NOT NULL,
                    company_domain VARCHAR(255),
                    role VARCHAR(255),
                    seniority VARCHAR(100),
                    department VARCHAR(100),
                    cached_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_cufinder_cache_key_tenant
                ON public.cufinder_cache(cache_key, tenant_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cufinder_cache_expires
                ON public.cufinder_cache(expires_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cufinder_cache_tenant
                ON public.cufinder_cache(tenant_id)
            """)

            logger.info("✓ cufinder_cache table and indexes ensured")
        except Exception as e:
            logger.warning(f"cufinder_cache table warning: {e}")

        # PHASE 2: ALTER EXISTING TABLES TO ADD MISSING COLUMNS
        # Note: PHASE 1 creates base tables; PHASE 2 handles schema evolution

        # 13. Ensure linkedin_handle column exists in prospects (should exist from CREATE TABLE)
        try:
            cursor.execute("""
                ALTER TABLE public.prospects
                ADD COLUMN IF NOT EXISTS linkedin_handle TEXT
            """)
            logger.info("✓ linkedin_handle column ensured")
        except Exception as e:
            logger.warning(f"linkedin_handle column migration warning: {e}")

        # 14. Ensure updated_at column exists in prospects (should exist from CREATE TABLE)
        try:
            cursor.execute("""
                ALTER TABLE public.prospects
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
            """)
            logger.info("✓ updated_at column ensured")
        except Exception as e:
            logger.warning(f"updated_at column migration warning: {e}")

        # 15. Backfill linkedin_handle from existing URLs
        try:
            cursor.execute(r"""
                UPDATE public.prospects
                SET linkedin_handle = LOWER(
                    REGEXP_REPLACE(
                        REGEXP_REPLACE(linkedin_url, '^https?://(www\.)?linkedin\.com/in/', ''),
                        '/+$', ''
                    )
                )
                WHERE linkedin_handle IS NULL
                  AND linkedin_url IS NOT NULL
            """)
            count = cursor.rowcount
            if count > 0:
                logger.info(f"✓ Backfilled {count} linkedin_handle values")
        except Exception as e:
            logger.warning(f"Backfill warning: {e}")

        # 16. Remove duplicates before creating unique index
        try:
            cursor.execute("""
                WITH duplicates AS (
                    SELECT id,
                           ROW_NUMBER() OVER (PARTITION BY tenant_id, linkedin_handle ORDER BY id) AS rn
                    FROM public.prospects
                    WHERE linkedin_handle IS NOT NULL
                )
                DELETE FROM public.prospects
                WHERE id IN (
                    SELECT id FROM duplicates WHERE rn > 1
                )
            """)
            count = cursor.rowcount
            if count > 0:
                logger.info(f"✓ Removed {count} duplicate prospects")
        except Exception as e:
            logger.warning(f"Duplicate removal warning: {e}")

        # 17. Create unique index on (tenant_id, linkedin_handle)
        try:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_prospects_tenant_handle
                ON public.prospects (tenant_id, linkedin_handle)
            """)
            logger.info("✓ Unique index on (tenant_id, linkedin_handle) ensured")
        except Exception as e:
            logger.warning(f"Unique index warning: {e}")

        # 18. Create additional performance index on linkedin_handle
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_prospects_linkedin_handle
                ON public.prospects (linkedin_handle)
            """)
            logger.info("✓ Performance index on linkedin_handle ensured")
        except Exception as e:
            logger.warning(f"Performance index warning: {e}")

        # 19. Add missing columns to job_runs table (idempotency support)
        try:
            # Add idempotency_key column to job_runs
            cursor.execute("""
                ALTER TABLE public.job_runs
                ADD COLUMN IF NOT EXISTS idempotency_key TEXT
            """)
            
            # Create unique index for idempotency
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS job_runs_idem_unique
                ON public.job_runs (tenant_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL
            """)
            
            logger.info("✓ job_runs idempotency_key column and index ensured")
        except Exception as e:
            logger.warning(f"job_runs idempotency warning: {e}")
        
        # 15. Create prospect_mutuals status columns for connector persistence
        try:
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'new' CHECK (status IN ('new','queued','contacted','failed'))
            """)
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS last_action_at TIMESTAMPTZ
            """)
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS introduction_id INTEGER
            """)
            
            logger.info("✓ prospect_mutuals status columns ensured")
        except Exception as e:
            logger.warning(f"prospect_mutuals status warning: {e}")
        
        # 16. Create triggers for updated_at
        tables_with_updated_at = ['prospects', 'tenant_settings', 'job_idempotency', 'provider_health', 'outreach_queue', 'daily_quotas', 'prospect_mutuals']
        for table in tables_with_updated_at:
            try:
                cursor.execute(f"""
                    DROP TRIGGER IF EXISTS update_{table}_updated_at ON public.{table}
                """)
                cursor.execute(f"""
                    CREATE TRIGGER update_{table}_updated_at
                    BEFORE UPDATE ON public.{table}
                    FOR EACH ROW EXECUTE FUNCTION set_updated_at()
                """)
                logger.info(f"✓ Trigger for {table}.updated_at ensured")
            except Exception as e:
                logger.warning(f"Trigger for {table} warning: {e}")
        
        # 17. Add missing uniqueness constraints to prevent duplicates
        try:
            # Unique constraint for prospect_mutuals to prevent duplicate mutual connections
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_prospect_mutuals_tenant_prospect_url
                ON public.prospect_mutuals (tenant_id, prospect_id, mutual_linkedin_url)
            """)
            logger.info("✓ Unique constraint on prospect_mutuals (tenant_id, prospect_id, mutual_linkedin_url) ensured")
            
            # Unique constraint for outreach_queue to prevent duplicate introductions
            # Use LOWER to make case-insensitive and canonicalize URLs
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_queue_tenant_prospect_connector
                ON public.outreach_queue (tenant_id, prospect_id, LOWER(connector_linkedin))
                WHERE connector_linkedin IS NOT NULL
            """)
            logger.info("✓ Unique constraint on outreach_queue (tenant_id, prospect_id, connector_linkedin) ensured")
            
            # Unique constraint for users email to prevent duplicate accounts
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email
                ON public.users (LOWER(email))
            """)
            logger.info("✓ Unique constraint on users (email) ensured")
            
            # Unique constraint for contacts to prevent duplicate team members per tenant
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_tenant_email
                ON public.contacts (tenant_id, LOWER(email))
                WHERE email IS NOT NULL
            """)
            logger.info("✓ Unique constraint on contacts (tenant_id, email) ensured")
            
            # Also add constraint for contacts LinkedIn URL
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_tenant_linkedin
                ON public.contacts (tenant_id, linkedin_url)
                WHERE linkedin_url IS NOT NULL
            """)
            logger.info("✓ Unique constraint on contacts (tenant_id, linkedin_url) ensured")
            
        except Exception as e:
            logger.warning(f"Uniqueness constraints warning: {e}")
        
        # 16. Add missing columns to prospect_mutuals table (GPT5's recommendation)
        try:
            # Add the missing columns that the API code expects
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS provider TEXT
            """)
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMPTZ
            """)
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS ranking_score DOUBLE PRECISION DEFAULT 0
            """)
            # New: Persist connector email to avoid re-running CUFinder and link to contacts
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS mutual_email TEXT
            """)
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS mutual_email_confidence DOUBLE PRECISION
            """)
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS email_enriched_at TIMESTAMPTZ
            """)
            cursor.execute("""
                ALTER TABLE public.prospect_mutuals
                ADD COLUMN IF NOT EXISTS contact_id INTEGER
            """)

            # Create useful indexes for performance and deduplication
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pm_tenant_prospect 
                ON public.prospect_mutuals (tenant_id, prospect_id)
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uniq_pm_conn
                ON public.prospect_mutuals (tenant_id, prospect_id, lower(mutual_linkedin_url))
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pm_ranking_score
                ON public.prospect_mutuals (ranking_score DESC NULLS LAST)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_pm_scraped_at
                ON public.prospect_mutuals (scraped_at DESC NULLS LAST)
            """)
            
            logger.info("✓ prospect_mutuals missing columns and indexes added")
        except Exception as e:
            logger.warning(f"prospect_mutuals columns warning: {e}")

        # 16b. Ensure contacts table has email metadata columns used by enrichment
        try:
            # Core identity columns that some older schemas may miss
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS full_name TEXT
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS linkedin_url TEXT
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS company TEXT
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS title TEXT
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS email_confidence DOUBLE PRECISION
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS email_last_verified TIMESTAMPTZ
            """)
            cursor.execute("""
                ALTER TABLE public.contacts
                ADD COLUMN IF NOT EXISTS email_source TEXT
            """)
            logger.info("✓ contacts email metadata columns ensured")
        except Exception as e:
            logger.warning(f"contacts metadata columns warning: {e}")
        
        # 16c. Ensure unique indexes compatible with ON CONFLICT clauses used in code
        try:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_tenant_email_plain
                ON public.contacts (tenant_id, email)
                WHERE email IS NOT NULL
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_tenant_linkedin_plain
                ON public.contacts (tenant_id, linkedin_url)
                WHERE linkedin_url IS NOT NULL
            """)
            logger.info("✓ contacts unique indexes for (tenant_id,email) and (tenant_id,linkedin_url) ensured")
        except Exception as e:
            logger.warning(f"contacts unique indexes warning: {e}")
        
        # 17. Fix job_runs table idempotency constraint (GPT5's recommendation)
        try:
            # Add idempotency_key column if missing
            cursor.execute("""
                ALTER TABLE public.job_runs
                ADD COLUMN IF NOT EXISTS idempotency_key TEXT
            """)
            
            # Create unique constraint for idempotency (if not exists)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS job_runs_idem_unique
                ON public.job_runs (tenant_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL
            """)
            
            logger.info("✓ job_runs idempotency constraint ensured")
        except Exception as e:
            logger.warning(f"job_runs idempotency constraint warning: {e}")
        
        logger.info("✅ All database migrations completed successfully")

        # 20. Create dev_mfa_tokens table if it doesn't exist
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.dev_mfa_tokens (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT,
                    account_id TEXT,
                    tenant_id TEXT,
                    otp_secret TEXT,
                    method TEXT,
                    delivery_channel TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            logger.info("✓ dev_mfa_tokens table ensured")
        except Exception as e:
            logger.warning(f"dev_mfa_tokens table warning: {e}")

        # 21. Create dev_sessions table if it doesn't exist
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.dev_sessions (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT,
                    account_id TEXT,
                    tenant_id TEXT,
                    device_id INTEGER,
                    effective_role TEXT,
                    permissions TEXT,
                    device_fingerprint TEXT,
                    idle_expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            logger.info("✓ dev_sessions table ensured")
        except Exception as e:
            logger.warning(f"dev_sessions table warning: {e}")

        # 22. Create billing_plans table if it doesn't exist (for company portal)
        try:
            logger.info("Creating billing_plans table...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.billing_plans (
                    tier TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    stripe_product_id TEXT NOT NULL,
                    stripe_price_id TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'usd',
                    interval TEXT NOT NULL DEFAULT 'month',
                    unit_amount INTEGER NOT NULL,
                    included_seats INTEGER NOT NULL DEFAULT 1,
                    max_seats INTEGER,
                    metadata TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            logger.info("✓ billing_plans table created")

            # Use CREATE UNIQUE INDEX IF NOT EXISTS instead of ALTER TABLE ADD CONSTRAINT
            # This is more idempotent and avoids the "Cannot add a UNIQUE column" error
            logger.info("Adding UNIQUE index to stripe_price_id...")
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS billing_plans_stripe_price_id_key
                ON public.billing_plans (stripe_price_id)
            """)
            logger.info("✓ billing_plans UNIQUE index ensured")
        except Exception as e:
            logger.warning(f"billing_plans table warning: {e}")
            import traceback
            logger.warning(f"billing_plans traceback: {traceback.format_exc()}")

        # 23. Fix user_preferences schema: add preferences JSONB column and update unique constraint
        try:
            logger.info("Fixing user_preferences schema...")

            # Add preferences JSONB column that application code expects
            cursor.execute("""
                ALTER TABLE user_preferences
                ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}'::jsonb
            """)
            logger.info("✓ user_preferences.preferences column ensured")

            # Drop old single-column unique constraint if it exists
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE table_name = 'user_preferences'
                        AND constraint_name = 'uq_user_preferences_user'
                        AND constraint_type = 'UNIQUE'
                    ) THEN
                        ALTER TABLE user_preferences DROP CONSTRAINT uq_user_preferences_user;
                    END IF;
                END $$;
            """)
            logger.info("✓ Dropped old user_preferences unique constraint (if existed)")

            # Add composite unique constraint on (tenant_id, user_id)
            cursor.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE table_name = 'user_preferences'
                        AND constraint_name = 'uq_user_preferences_tenant_user'
                        AND constraint_type = 'UNIQUE'
                    ) THEN
                        ALTER TABLE user_preferences
                        ADD CONSTRAINT uq_user_preferences_tenant_user UNIQUE (tenant_id, user_id);
                    END IF;
                END $$;
            """)
            logger.info("✓ user_preferences unique constraint (tenant_id, user_id) ensured")

        except Exception as e:
            logger.warning(f"user_preferences schema fix warning: {e}")
            import traceback
            logger.warning(f"user_preferences traceback: {traceback.format_exc()}")

    except Exception as e:
        logger.error(f"Migration runner failed: {e}")
        import traceback
        logger.error(f"Migration traceback: {traceback.format_exc()}")
        # Re-raise the exception to properly signal initialization failure
        raise
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

    logger.info("🎯 run_all_migrations() function is RETURNING NOW")
    import sys
    sys.stdout.flush()

if __name__ == "__main__":
    import os
    import sys

    try:
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(levelname)s:%(name)s:%(message)s'
        )

        # Get database URL from environment
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            logger.error("DATABASE_URL environment variable not set")
            sys.exit(1)

        logger.info("Starting database migrations...")
        sys.stdout.flush()
        run_all_migrations(database_url)
        logger.info("Database migrations completed")
        sys.stdout.flush()

        # After migrations, exec run_server.py to bypass Dashboard's hardcoded uvicorn command
        # This ensures we use the correct dynamic PORT from environment
        logger.info("Starting server via run_server.py wrapper...")
        sys.stdout.flush()

        # Get absolute path to run_server.py (one directory up from api/)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        server_script = os.path.join(script_dir, "..", "run_server.py")
        server_script = os.path.abspath(server_script)  # Normalize the path

        logger.info(f"Executing: python {server_script}")
        sys.stdout.flush()
        os.execvp("python", ["python", server_script])
    except Exception as e:
        logger.error(f"FATAL ERROR in __main__: {e}")
        sys.stdout.flush()
        import traceback
        traceback.print_exc()
        sys.exit(1)
