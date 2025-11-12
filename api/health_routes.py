from __future__ import annotations
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Header
import asyncpg
from services.asyncpg_rls import acquire_conn

router = APIRouter(prefix="/api")


def _provider_status() -> Dict[str, Any]:
    def present(env: str) -> bool:
        return bool(os.getenv(env, "").strip())
    return {
        "apify": {"configured": present("APIFY_TOKEN")},
        "cufinder": {"configured": present("CUFINDER_API_KEY")},
        "sendgrid": {"configured": present("SENDGRID_API_KEY")},
        "phantom": {"configured": present("PHANTOMBUSTER_API_KEY")},
    }


@router.get("/health")
async def health() -> Dict[str, Any]:
    providers = _provider_status()
    model = os.getenv("PRIMARY_MODEL", "")
    status = "healthy" if all(v.get("configured") for v in providers.values() if v) else "degraded"
    return {
        "status": status,
        "version": os.getenv("SERVICE_VERSION", "dev"),
        "model": model,
        "providers": providers,
        "schema": {},  # optionally fill with presence checks
    }


@router.post("/preflight/providers")
async def preflight_providers(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    include = set((body or {}).get("include", [])) if body else set()
    status = _provider_status()
    result: Dict[str, Any] = {}
    for name in ("apify", "cufinder", "sendgrid", "phantom"):
        if include and name not in include:
            continue
        result[name] = {**status.get(name, {}), "ok": status.get(name, {}).get("configured", False)}
    return result


@router.get("/db/context")
async def db_context(x_organization_id: Optional[int] = Header(None)) -> Dict[str, Any]:
    """Debug endpoint: returns current tenant/organization GUC values.

    In production, ensure proper auth in front of this endpoint if exposed.
    """
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        return {"error": "DATABASE_URL not configured"}

    tenant = str(x_organization_id) if x_organization_id is not None else None

    async with acquire_conn(dsn, tenant) as conn:
        tenant_guc = await conn.fetchval("SELECT current_setting('app.current_tenant_id', true)")
        org_guc = await conn.fetchval("SELECT current_setting('app.current_organization_id', true)")
        return {
            "tenant_id": tenant_guc,
            "organization_id": org_guc,
        }


@router.get("/db/probe")
async def db_probe(x_organization_id: Optional[int] = Header(None)) -> Dict[str, Any]:
    """Debug endpoint: probes a few RLS tables and returns record counts for the tenant.

    Gate with ALLOW_DB_PROBE (any truthy value). Intended for staging/ops.
    """
    if not os.getenv("ALLOW_DB_PROBE"):
        return {"error": "db probe disabled; set ALLOW_DB_PROBE to enable"}

    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        return {"error": "DATABASE_URL not configured"}

    tenant = str(x_organization_id) if x_organization_id is not None else None
    results: Dict[str, Any] = {"tenant": tenant}

    async with acquire_conn(dsn, tenant) as conn:
        # Verify context
        results["tenant_guc"] = await conn.fetchval("SELECT current_setting('app.current_tenant_id', true)")
        results["organization_guc"] = await conn.fetchval("SELECT current_setting('app.current_organization_id', true)")

        async def count_if_exists(table: str, where: str) -> Optional[int]:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='public' AND table_name=$1
                )
                """,
                table,
            )
            if not exists:
                return None
            try:
                return await conn.fetchval(f"SELECT COUNT(*) FROM {table} WHERE {where}")
            except Exception:
                return None

        # Probe a small set of tables commonly used by the app
        results["counts"] = {
            "prospects": await count_if_exists("prospects", "tenant_id = current_setting('app.current_tenant_id', true)::int"),
            "approval_requests": await count_if_exists("approval_requests", "organization_id = current_setting('app.current_tenant_id', true)::int"),
            "prospect_mutuals": await count_if_exists("prospect_mutuals", "tenant_id = current_setting('app.current_tenant_id', true)::int"),
            "connectors": await count_if_exists("connectors", "organization_id = current_setting('app.current_tenant_id', true)::int"),
        }

    return results
