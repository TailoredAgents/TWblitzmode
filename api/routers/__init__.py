"""Router packages for the unified FastAPI application.

Phase 3 scaffolding: hosts feature-flagged routers that will gradually
replace legacy entrypoints (e.g., `api.introducers_app`).  Routes remain
intentionally thin so they can be mounted from `api.main` with minimal
side effects.
"""

from fastapi import APIRouter


def create_placeholder_router(*, tag: str, name: str) -> APIRouter:
    """Utility to build an empty router with shared metadata."""
    return APIRouter(tags=[tag], prefix="")


__all__ = ["create_placeholder_router"]
