"""
Health routes example for the new repo.

Exposes GET /api/health and POST /api/preflight/providers as outlined in blitz/openapi.yaml.
"""
from __future__ import annotations
import os
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter

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
    schema = {
        # Placeholder: fill with real checks in implementation
        "users": "unknown",
        "team_members": "unknown",
    }
    model = os.getenv("PRIMARY_MODEL", "")
    status = "healthy" if all(v.get("configured") for v in providers.values() if v) else "degraded"
    return {
        "status": status,
        "version": os.getenv("SERVICE_VERSION", "dev"),
        "model": model,
        "providers": providers,
        "schema": schema,
    }


@router.post("/preflight/providers")
async def preflight_providers(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    include = set((body or {}).get("include", [])) if body else set()
    # Call out to the utility script or reimplement simple HTTP checks here
    # Return a shape compatible with the OpenAPI spec
    result: Dict[str, Any] = {}
    t0 = time.time()
    status = _provider_status()
    for name in ("apify", "cufinder", "sendgrid", "phantom"):
        if include and name not in include:
            continue
        result[name] = {**status.get(name, {}), "ok": status.get(name, {}).get("configured", False)}
    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result

