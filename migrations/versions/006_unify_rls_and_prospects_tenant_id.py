"""Unify RLS to single GUC and add prospects.tenant_id

Revision ID: 006_unify_rls_and_prospects_tenant_id
Revises: 005_port_legacy_tables
Create Date: 2025-11-12 12:45:00.000000

This migration standardizes row-level security (RLS) to a single GUC
`app.current_tenant_id` across multi-tenant tables and adds a `tenant_id`
column to the corporate `prospects` table (backfilled from `organization_id`).
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "006_unify_rls_and_prospects_tenant_id"
down_revision = "005_port_legacy_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add tenant_id to prospects (corporate) and backfill from organization_id
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='prospects' AND column_name='tenant_id'
            ) THEN
                ALTER TABLE public.prospects ADD COLUMN tenant_id INTEGER;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        UPDATE public.prospects
        SET tenant_id = organization_id
        WHERE tenant_id IS NULL AND organization_id IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prospects_tenant ON public.prospects (tenant_id);
        """
    )

    # Ensure unique handle index when linkedin_handle column is present
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='prospects' AND column_name='linkedin_handle'
            ) THEN
                EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_prospects_tenant_handle ON public.prospects (tenant_id, linkedin_handle)';
            END IF;
        END $$;
        """
    )

    # 2) Unify RLS policies to app.current_tenant_id for all known multi-tenant tables
    # We'll enable/force RLS and replace existing policies with a single unified policy
    # using either organization_id or tenant_id depending on table structure.
    op.execute(
        """
        DO $$
        DECLARE
            t RECORD;
            pol RECORD;
            tenant_col TEXT;
            target_tables TEXT[] := ARRAY[
                'organizations','team_members','integration_sets','cookie_jars','prospects',
                'connectors','prospect_connectors','email_templates','email_jobs','approval_requests',
                'job_idempotency','organization_metrics','audit_events',
                -- legacy/runner tables
                'tenant_settings','contacts','prospect_mutuals','outreach_queue','job_runs',
                'users','provider_health','daily_quotas','auth_sessions','cufinder_cache','user_preferences'
            ];
        BEGIN
            FOREACH tenant_col IN ARRAY ARRAY['organization_id','tenant_id'] LOOP END LOOP; -- avoid unused warning

            FOR t IN SELECT unnest(target_tables) AS table_name LOOP
                -- skip if table is absent
                IF to_regclass(format('public.%I', t.table_name)) IS NULL THEN
                    CONTINUE;
                END IF;

                -- Enable and force RLS
                EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.table_name);
                EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t.table_name);

                -- Determine tenant discriminator column
                SELECT CASE
                    WHEN EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name=t.table_name AND column_name='organization_id'
                    ) THEN 'organization_id'
                    WHEN EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name=t.table_name AND column_name='tenant_id'
                    ) THEN 'tenant_id'
                    ELSE NULL
                END INTO tenant_col;

                IF tenant_col IS NULL THEN
                    CONTINUE;
                END IF;

                -- Drop existing policies on the table
                FOR pol IN SELECT polname FROM pg_policies WHERE schemaname='public' AND tablename=t.table_name LOOP
                    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', pol.polname, t.table_name);
                END LOOP;

                -- Create unified policy bound to app.current_tenant_id
                EXECUTE format(
                    'CREATE POLICY rls_unified_%I ON public.%I USING (%I = current_setting(''app.current_tenant_id'', true)::integer)',
                    t.table_name, t.table_name, tenant_col
                );
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Best-effort revert: drop unified policies (leaves RLS enabled) and remove prospects.tenant_id
    op.execute(
        """
        DO $$
        DECLARE
            t RECORD;
            polname TEXT;
        BEGIN
            FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
                polname := 'rls_unified_' || t.tablename;
                EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', polname, t.tablename);
            END LOOP;
        END $$;
        """
    )

    op.execute(
        """
        ALTER TABLE IF EXISTS public.prospects DROP COLUMN IF EXISTS tenant_id;
        """
    )
