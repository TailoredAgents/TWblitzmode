"""Port essential legacy tables into Alembic

Revision ID: 005_port_legacy_tables
Revises: 004_database_normalization
Create Date: 2025-11-12 12:30:00.000000

This migration folds critical tables historically created by ad-hoc runners
into the Alembic-controlled schema to reduce drift and ensure deterministic
startup on Render.
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "005_port_legacy_tables"
down_revision = "004_database_normalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # auth_sessions
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_tenant ON public.auth_sessions (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON public.auth_sessions (user_id);
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_session ON public.auth_sessions (session_id);
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON public.auth_sessions (expires_at);
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_revoked ON public.auth_sessions (revoked_at);
        """
    )

    # daily_quotas
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_daily_quotas_tenant_date
        ON public.daily_quotas (tenant_id, date);
        """
    )

    # provider_health
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_provider_health_tenant ON public.provider_health (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_provider_health_provider ON public.provider_health (provider);
        CREATE INDEX IF NOT EXISTS idx_provider_health_error_type ON public.provider_health (error_type);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_health_tenant_provider_type
        ON public.provider_health (tenant_id, provider, error_type);
        """
    )

    # outreach_queue
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_outreach_queue_tenant_id ON public.outreach_queue (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_queue_status ON public.outreach_queue (status);
        CREATE INDEX IF NOT EXISTS idx_outreach_queue_prospect_id ON public.outreach_queue (prospect_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_queue_tenant_prospect_connector
        ON public.outreach_queue (tenant_id, prospect_id, LOWER(connector_linkedin))
        WHERE connector_linkedin IS NOT NULL;
        """
    )

    # users
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON public.users (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_users_email ON public.users (LOWER(email));
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_email ON public.users (tenant_id, LOWER(email));
        """
    )

    # cufinder_cache
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cufinder_cache_key_tenant ON public.cufinder_cache(cache_key, tenant_id);
        CREATE INDEX IF NOT EXISTS idx_cufinder_cache_expires ON public.cufinder_cache(expires_at);
        CREATE INDEX IF NOT EXISTS idx_cufinder_cache_tenant ON public.cufinder_cache(tenant_id);
        """
    )

    # user_preferences (compact variant aligned with API usage)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.user_preferences (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tenant_id, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_preferences_tenant ON public.user_preferences(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_user_preferences_user ON public.user_preferences(user_id);
        """
    )


def downgrade() -> None:
    # Drop in reverse order
    op.execute("DROP TABLE IF EXISTS public.user_preferences")
    op.execute("DROP TABLE IF EXISTS public.cufinder_cache")
    op.execute("DROP TABLE IF EXISTS public.users")
    op.execute("DROP TABLE IF EXISTS public.outreach_queue")
    op.execute("DROP TABLE IF EXISTS public.provider_health")
    op.execute("DROP TABLE IF EXISTS public.daily_quotas")
    op.execute("DROP TABLE IF EXISTS public.auth_sessions")

