# FastAPI Startup Integration (Copy/Paste)

This shows exactly how to wire JSON logging with correlation IDs and health/preflight routes into a typical FastAPI `api/main.py` for the Blitz repo.

Minimal app/main.py

```python
# api/main.py
from fastapi import FastAPI
from blitz.examples.api.logging_middleware import setup_json_logging, logging_middleware
from blitz.examples.api.health_routes import router as health_router
import os

# Configure service metadata for logs/health
os.environ.setdefault("SERVICE_NAME", "link-api")
# Recommended to inject a build SHA at deploy time
os.environ.setdefault("SERVICE_VERSION", os.getenv("GIT_SHA", "dev"))

# Set up logging
setup_json_logging()

app = FastAPI(title="Link Blitz API", version=os.getenv("SERVICE_VERSION", "dev"))

# Correlation-aware logging for all HTTP requests
app.middleware("http")(logging_middleware)

# Health + preflight endpoints
app.include_router(health_router)

@app.get("/")
async def root():
    return {"message": "Link Blitz API", "version": os.getenv("SERVICE_VERSION", "dev")}
```

Notes

- `setup_json_logging()` enables JSON logs when `LOG_FORMAT=json` (recommended in Render).
- `logging_middleware` generates/propagates `X-Correlation-Id`, logs route/method/status/latency, and echoes corr_id back in the response header.
- `health_router` exposes `GET /api/health` and `POST /api/preflight/providers` as defined in `blitz/openapi.yaml`.
- Set `SERVICE_NAME` and `SERVICE_VERSION` (e.g., from a git SHA) to appear in all log lines and `/api/health`.

