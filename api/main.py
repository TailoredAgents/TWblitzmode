from __future__ import annotations
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.logging_middleware import setup_json_logging, logging_middleware
from api.health_routes import router as health_router

# Select Link routers only (no legacy auth/admin/dev-portal)
from api.routes_email import router as email_router
from api.routes_email_webhooks import router as email_webhooks_router
from api.routes_linkedin import router as linkedin_router
from api.routes_prospects import router as prospects_router
from api.routes_connectors import router as connectors_router
from api.routes_ai_orchestration import router as ai_router
from api.routes_agent_events import router as agent_events_router
from api.routes_team import router as team_router


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

# Link feature routers
app.include_router(email_router, prefix="/api")
app.include_router(email_webhooks_router, prefix="/api")
app.include_router(linkedin_router, prefix="/api")
app.include_router(prospects_router, prefix="/api")
app.include_router(connectors_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(agent_events_router, prefix="/api")
app.include_router(team_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Link Blitz API", "version": os.getenv("SERVICE_VERSION", "dev")}

