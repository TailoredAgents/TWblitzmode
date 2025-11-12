"""
Startup sanity checks to prevent tenant/organization FK mismatches.

This module ensures that the default tenant/organization pair exists and is
aligned before the application begins serving traffic. It mirrors the roster
bootstrap logic without creating any user accounts.
"""

from __future__ import annotations

import logging
import os
from typing import Tuple

from core.settings import settings
from .db_core import get_conn, execute

logger = logging.getLogger(__name__)


def ensure_default_tenant_org_alignment() -> Tuple[int, int]:
    """
    Ensure a default tenant (id=1) and organization (id=1) exist and are aligned.

    Returns a tuple of (tenant_id, organization_id).
    """
    tenant_name = os.getenv("CLIENT_NAME", "Tallwave").strip() or "Tallwave"
    default_slug = (getattr(settings, "DEFAULT_ORGANIZATION_SLUG", "tallwave") or "tallwave").strip().lower()
    default_domain = getattr(settings, "DEFAULT_ORGANIZATION_DOMAIN", None) or "tallwave.com"

    with get_conn() as conn:
        try:
            # Create minimal core tables if missing; IF NOT EXISTS is safe to run repeatedly
            conn.cursor().execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.cursor().execute(
                """
                CREATE TABLE IF NOT EXISTS organizations (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE,
                    domain TEXT,
                    subscription_tier TEXT DEFAULT 'enterprise',
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        except Exception:
            # If migrations manage schema, these may fail in some environments; continue
            conn.rollback()

        # Align default records using UPSERTs
        desired_id = 1
        execute(
            conn,
            """
            INSERT INTO tenants (id, name, status)
            VALUES (%s, %s, 'active')
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                status = 'active'
            """,
            (desired_id, tenant_name),
        )

        execute(
            conn,
            """
            INSERT INTO organizations (
                id,
                tenant_id,
                name,
                slug,
                domain,
                subscription_tier,
                status
            )
            VALUES (%s, %s, %s, %s, %s, 'enterprise', 'active')
            ON CONFLICT (id) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                name = EXCLUDED.name,
                slug = EXCLUDED.slug,
                domain = EXCLUDED.domain,
                subscription_tier = EXCLUDED.subscription_tier,
                status = 'active',
                updated_at = NOW()
            """,
            (desired_id, desired_id, tenant_name, default_slug, default_domain),
        )

        logger.info(
            "Default tenant/org alignment ensured (tenant_id=%s, organization_id=%s)",
            desired_id,
            desired_id,
        )

        return desired_id, desired_id

