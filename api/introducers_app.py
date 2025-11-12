"""Deprecated legacy entrypoint for backwards compatibility.

Historically, `api.introducers_app` hosted a standalone FastAPI application
with bespoke middleware and routes.  Those endpoints now live behind feature
flags in ``api.main`` via the `legacy_introducers` and `legacy_automation`
routers.  This module simply re-exports the unified app so existing deployment
scripts that still reference ``api.introducers_app:app`` keep working during the
transition.
"""

from api.main import app  # re-export canonical application

__all__ = ["app"]
