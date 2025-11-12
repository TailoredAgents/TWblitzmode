from __future__ import annotations
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.logging_middleware import setup_json_logging, logging_middleware
from api.health_routes import router as health_router


def _allowed_origins() -> list[str]:
    origins = set(
        filter(
            None,
            [
                os.getenv("NEXT_PUBLIC_SITE_URL"),
                os.getenv("NEXT_PUBLIC_API_URL"),
                "http://localhost:3000",
            ],
        )
    )
    extra = os.getenv("CORS_ORIGINS", "")
    for token in extra.split(","):
        token = token.strip()
        if token:
            origins.add(token)
    return sorted(origins)


# Service metadata
os.environ.setdefault("SERVICE_NAME", "link-api")
os.environ.setdefault("SERVICE_VERSION", os.getenv("GIT_SHA", "dev"))

setup_json_logging()

app = FastAPI(title="Link Blitz API", version=os.getenv("SERVICE_VERSION", "dev"))

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation-aware logging
app.middleware("http")(logging_middleware)

# Health & preflight
app.include_router(health_router)

# Link feature routers (optional in constrained envs)
if os.getenv("MINIMAL_ROUTERS_ONLY", "").lower() not in ("1", "true", "yes"):  # pragma: no cover - runtime wiring
    log = logging.getLogger(__name__)
    def _try_include(module_path: str, router_name: str = "router") -> None:
        try:
            module = __import__(module_path, fromlist=[router_name])
            router = getattr(module, router_name)
            app.include_router(router, prefix="/api")
        except Exception as e:
            log.warning("Skipping %s due to import error: %s", module_path, e)

    # Select Link routers only (no legacy auth/admin/dev-portal)
    for mod in (
        "api.routes_email",
        "api.routes_email_webhooks",
        "api.routes_linkedin",
        "api.routes_prospects",
        "api.routes_connectors",
        "api.routes_ai_orchestration",
        "api.routes_agent_events",
        "api.routes_team",
    ):
        _try_include(mod)


@app.get("/")
async def root():
    return {"message": "Link Blitz API", "version": os.getenv("SERVICE_VERSION", "dev")}
