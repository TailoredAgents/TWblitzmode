from __future__ import annotations
import os
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

