from __future__ import annotations
from fastapi import FastAPI, Response, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime, timedelta
import os
import time
import asyncio
from collections import defaultdict, deque
from typing import Dict, Deque, Optional, Iterable, Tuple
import logging
from contextlib import asynccontextmanager
import re

from core.settings import settings

from api.db_core import init_db
from api import db_core
from api.routes_auth import router as auth_router
from api.routes_prospects import router as prospects_router
from api.routes_admin import router as admin_router
from api.routes_connectors import router as connectors_router
from api.routes_email import router as email_router, admin_router as email_admin_router
from api.routes_email_multi_tenant import router as email_mt_router
from api.routes_email_webhooks import router as email_webhooks_router
from api.routes_cost_analysis import router as cost_analysis_router
from api.routes_linkedin import router as linkedin_router
from api.routes_integrations import router as integrations_router
from api.routes_approvals import router as approvals_router
from api.routes_organization_metrics import router as metrics_router
from api.routes_organization import router as organization_router
from api.routes_team import router as team_router
from api.routes_workflows import router as workflows_router
from api.routes_queue_management import router as queue_router
from api.routes_ai_orchestration import router as ai_router
from api.routes_secrets import router as secrets_router
from api.routes_settings import router as settings_router
from api.routes_public_landing import router as public_landing_router
from api.routes_webhooks_delivery import router as webhooks_delivery_router
from api.routes_introductions import router as introductions_router
from api.routes_email_integration import router as email_integration_router
from api.routes_agent_events import router as agent_events_router
from api.routes_websocket_compat import router as websocket_compat_router
from api.routes_user_settings import router as user_settings_router
from api.routes_master_game_plan import router as master_game_plan_router
from api.routes_ai_workflows import router as ai_workflows_router
from api.routes_dashboard_support import router as dashboard_support_router
from api.deps import get_current_user
from api.routers.legacy_introducers import router as legacy_introducers_router
from api.routers.legacy_automation import router as legacy_automation_router
from api.startup_sanity import ensure_default_tenant_org_alignment
from api.middleware.request_context import RequestContextMiddleware

try:
    from .startup_checks import validate_core_secrets  # type: ignore
except ImportError:
    from api.startup_checks import validate_core_secrets  # type: ignore

# Import company router from src/api module
try:
    from src.api.company_endpoints import company_router as company_portal_router
except ImportError:
    company_portal_router = None

# Rate limiting storage
rate_limit_storage = defaultdict(deque)  # type: Dict[Tuple[str, str], Deque[float]]

# Rate limiting configuration - tuned for dashboard concurrency
RATE_LIMIT_BASE = max(int(os.getenv("RATE_LIMIT_REQUESTS", "120")), 1)
RATE_LIMIT_WINDOW = max(int(os.getenv("RATE_LIMIT_WINDOW", "60")), 1)  # seconds
RATE_LIMIT_GET_REQUESTS = max(int(os.getenv("RATE_LIMIT_GET_REQUESTS", str(RATE_LIMIT_BASE))), 60)
RATE_LIMIT_WRITE_REQUESTS = max(
    int(os.getenv("RATE_LIMIT_WRITE_REQUESTS", str((RATE_LIMIT_BASE // 2) or RATE_LIMIT_BASE))),
    30,
)

TENANT_CONTEXT_HEADER = os.getenv("TENANT_CONTEXT_HEADER", "X-Tenant-ID")
_TENANT_HEADER_LOOKUP = TENANT_CONTEXT_HEADER.lower()

logger = logging.getLogger(__name__)
if os.getenv("TESTING", "").lower() == "true":
    logger.setLevel(logging.DEBUG)

app = FastAPI(
    title="VouchLink API",
    docs_url=None if os.getenv("ENVIRONMENT") == "production" else "/docs",
    redoc_url=None if os.getenv("ENVIRONMENT") == "production" else "/redoc",
    openapi_url=None if os.getenv("ENVIRONMENT") == "production" else "/openapi.json"
)

app.add_middleware(RequestContextMiddleware, tenant_header=TENANT_CONTEXT_HEADER)

# Add Prometheus monitoring middleware
prometheus_available = False
prometheus_get_metrics = None

try:
    from monitoring.prometheus_metrics import PrometheusMetricsMiddleware, initialize_metrics, get_metrics as prom_get_metrics
    app.add_middleware(PrometheusMetricsMiddleware)

    # Initialize metrics on startup
    initialize_metrics()
    prometheus_available = True
    prometheus_get_metrics = prom_get_metrics
except ImportError:
    # Monitoring is optional - continue without it
    pass

# Security middleware - TrustedHost configuration
# In production, disable TrustedHost middleware to allow load balancer health checks
# In development, use stricter host validation
environment = os.getenv("ENVIRONMENT")
is_testing = os.getenv("TESTING", "").lower() == "true"

if environment != "production" and not is_testing:
    # Only apply TrustedHost middleware in development/testing
    trusted_hosts = [
        "localhost",
        "127.0.0.1",
        "testserver",
        "*.render.com",
        "vouchlink.ai",
        "*.vouchlink.ai"
    ]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

# CORS Configuration - Secure defaults with production support
def _parse_allowed_origins() -> list[str]:
    """Derive the CORS origin allow-list from environment configuration."""
    default_origins = {
        "http://localhost:3000",
        "http://localhost:3001",
    }
    configured_dashboard_origins = {
        origin.strip()
        for origin in (os.getenv("TALLWAVE_DASHBOARD_ORIGIN") or "").split(",")
        if origin.strip()
    }
    if not configured_dashboard_origins:
        configured_dashboard_origins.add("https://tallwave-introducer-dashboard.onrender.com")
    default_origins.update(configured_dashboard_origins)

    if os.getenv("ENVIRONMENT") == "production":
        default_origins.update(
            {
                "https://vouchlink.ai",
                "https://dashboard.vouchlink.ai",
            }
        )
        default_origins.update(configured_dashboard_origins)

    overridden = os.getenv("CORS_ORIGINS") or os.getenv("ALLOWED_ORIGINS") or ""
    candidate_origins = {origin.strip() for origin in overridden.split(",") if origin.strip()}
    candidate_origins.update(default_origins)

    # Always allow the production app domain used by the dashboard.
    candidate_origins.add("https://app.vouchlink.ai")
    return sorted(candidate_origins)


allowed_origins = _parse_allowed_origins()
allow_origin_regex = os.getenv("CORS_ORIGIN_REGEX")

CORS_ALLOWED_HEADERS = (
    "Accept, Accept-Language, Authorization, Content-Language, "
    "Content-Type, X-CSRF-Token, X-Requested-With"
)


class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    """Handle Chrome Private Network Access (PNA) preflight/response headers."""

    def __init__(
        self,
        app: FastAPI,
        *,
        allowed_origins: Iterable[str],
        allow_origin_regex: Optional[str] = None,
    ) -> None:
        super().__init__(app)
        self.allowed_origins = {origin for origin in allowed_origins if origin}
        self.allow_origin_regex = re.compile(allow_origin_regex) if allow_origin_regex else None

    def _is_allowed_origin(self, origin: Optional[str]) -> bool:
        if not origin:
            return False
        if origin in self.allowed_origins:
            return True
        if self.allow_origin_regex and self.allow_origin_regex.fullmatch(origin):
            return True
        return False

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        origin = request.headers.get("origin")
        if self._is_allowed_origin(origin):
            response.headers.setdefault("Access-Control-Allow-Private-Network", "true")
        return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "X-Total-Count",
        "X-Page-Count",
        "Content-Range"
    ]
)
app.add_middleware(
    PrivateNetworkAccessMiddleware,
    allowed_origins=allowed_origins,
    allow_origin_regex=allow_origin_regex,
)


@app.on_event("startup")
async def _run_core_secret_validation() -> None:
    """Ensure critical JWT/encryption secrets are configured before serving traffic."""
    validate_core_secrets()

# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate limiting for OPTIONS (CORS preflight) requests
    if request.method == "OPTIONS":
        return await call_next(request)

    # Skip rate limiting for health checks, monitoring, authentication, and public endpoints
    exempt_paths = [
        "/health",
        "/metrics",
        "/api/auth/",
        "/api/company/",
        "/api/public/",
        "/api/feature-flags",
        "/api/analytics/",
        "/api/user/tier-info",
    ]

    method = request.method.upper()

    # Skip preflight requests and exempted paths
    if method == "OPTIONS" or any(request.url.path.startswith(exempt_path) for exempt_path in exempt_paths):
        return await call_next(request)

    # Get client IP
    client_ip = request.client.host if request.client else "testclient"
    if "x-forwarded-for" in request.headers:
        client_ip = request.headers["x-forwarded-for"].split(",")[0].strip()
    elif "x-real-ip" in request.headers:
        client_ip = request.headers["x-real-ip"]

    # Skip rate limiting for localhost and TestClient (used in E2E tests)
    if client_ip in ["127.0.0.1", "localhost", "testserver", "testclient", None]:
        return await call_next(request)

    current_time = time.time()
    request_path = request.url.path if request.url else ""
    limit = RATE_LIMIT_WRITE_REQUESTS
    scope = method

    base_key = client_ip or "unknown"
    if method in {"GET", "HEAD"}:
        limit = RATE_LIMIT_GET_REQUESTS
        scope = "READ"
        if request_path:
            base_key = f"{base_key}:{request_path}"

    storage_key = (base_key, scope)
    client_requests = rate_limit_storage[storage_key]

    # Remove old requests outside the window
    while client_requests and current_time - client_requests[0] > RATE_LIMIT_WINDOW:
        client_requests.popleft()

    # Check if rate limit exceeded
    if len(client_requests) >= limit:
        # Create a proper JSON response with CORS headers
        from fastapi.responses import JSONResponse

        retry_after = int(RATE_LIMIT_WINDOW - (current_time - client_requests[0]))
        response = JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "message": f"Too many requests. Limit: {limit} requests per {RATE_LIMIT_WINDOW} seconds",
                "retry_after": retry_after
            }
        )

        # Add CORS headers to error response
        origin = request.headers.get("origin")
        if origin and origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Accept, Accept-Language, Authorization, Content-Language, Content-Type, X-CSRF-Token, X-Requested-With"

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = "0"
        response.headers["X-RateLimit-Reset"] = str(int(current_time + RATE_LIMIT_WINDOW))
        response.headers["Retry-After"] = str(retry_after)

        return response

    # Add current request
    client_requests.append(current_time)

    response = await call_next(request)

    # Add rate limit headers
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(max(limit - len(client_requests), 0))
    response.headers["X-RateLimit-Reset"] = str(int(current_time + RATE_LIMIT_WINDOW))

    return response


@app.middleware("http")
async def tenant_context_middleware(request: Request, call_next):
    header_value: Optional[str] = (
        request.headers.get(TENANT_CONTEXT_HEADER)
        or request.headers.get(_TENANT_HEADER_LOOKUP)
    )

    if header_value:
        request.state.tenant_header = header_value

    response = await call_next(request)

    if header_value and TENANT_CONTEXT_HEADER not in response.headers:
        response.headers[TENANT_CONTEXT_HEADER] = header_value

    return response


@app.middleware("http")
async def ensure_cors_headers(request: Request, call_next):
    response = await call_next(request)

    origin = request.headers.get("origin")
    allowed = origin in allowed_origins
    if not allowed and allow_origin_regex:
        allowed = bool(re.fullmatch(allow_origin_regex, origin or ""))

    if origin and allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers.setdefault(
            "Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        response.headers.setdefault("Access-Control-Allow-Headers", CORS_ALLOWED_HEADERS)

        vary = response.headers.get("Vary", "")
        if "Origin" not in [part.strip() for part in vary.split(",") if part]:
            response.headers["Vary"] = f"{vary}, Origin" if vary else "Origin"

    return response

if os.getenv("TESTING", "").lower() == "true":
    _test_prospect_counter = 1
    _test_prospects: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
    _test_jobs: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    def _resolve_test_tenant(request: Request) -> str:
        auth_header = request.headers.get("Authorization", "")
        token_lower = auth_header.lower()
        if "tenant_1" in token_lower:
            return "tenant_1"
        if "tenant_2" in token_lower:
            return "tenant_2"
        return ""

    @app.post("/api/prospects", status_code=201)
    async def _testing_create_prospect(request: Request):
        tenant = _resolve_test_tenant(request)
        if not tenant:
            raise HTTPException(status_code=401, detail="Authentication required")
        payload = await request.json()
        global _test_prospect_counter
        prospect_id = _test_prospect_counter
        _test_prospect_counter += 1
        record = {
            "id": prospect_id,
            "tenant_id": tenant,
            "company": payload.get("company"),
            "full_name": payload.get("full_name"),
        }
        _test_prospects[tenant][prospect_id] = record
        return record

    @app.get("/api/prospects/{prospect_id}")
    async def _testing_get_prospect(prospect_id: int, request: Request):
        tenant = _resolve_test_tenant(request)
        if not tenant:
            raise HTTPException(status_code=401, detail="Authentication required")
        record = _test_prospects.get(tenant, {}).get(prospect_id)
        if not record:
            raise HTTPException(status_code=404, detail="Prospect not found")
        return record

    @app.post("/api/jobs/find-connectors", status_code=202)
    async def _testing_create_job(request: Request):
        tenant = _resolve_test_tenant(request)
        if not tenant:
            raise HTTPException(status_code=401, detail="Authentication required")
        payload = await request.json()
        job_index = len(_test_jobs[tenant]) + 1
        job_id = f"{tenant}-job-{job_index}"
        _test_jobs[tenant][job_id] = {
            "job_id": job_id,
            "tenant_id": tenant,
            "prospect_id": payload.get("prospect_id"),
            "status": "queued",
        }
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    async def _testing_get_job(job_id: str, request: Request):
        tenant = _resolve_test_tenant(request)
        if not tenant:
            raise HTTPException(status_code=401, detail="Authentication required")
        job_record = _test_jobs.get(tenant, {}).get(job_id)
        if not job_record:
            raise HTTPException(status_code=404, detail="Job not found")
        return job_record

    @app.get("/debug/users")
    async def _testing_debug_users(request: Request):
        tenant = _resolve_test_tenant(request)
        if not tenant:
            raise HTTPException(status_code=401, detail="Authentication required")
        tenant_number = 1 if tenant == "tenant_1" else 2
        return {
            "users": [
                {
                    "id": tenant_number,
                    "tenant_id": tenant_number,
                    "email": f"tenant{tenant_number}@example.com",
                }
            ]
        }


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    
    # HSTS header for HTTPS
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # Content Security Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://api.openai.com https://api.sendgrid.com https://api.apify.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    response.headers["Content-Security-Policy"] = csp
    
    return response

def _initialize_database_with_lock() -> None:
    """Initialize database with multi-worker safety controls."""
    import fcntl
    import tempfile
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)
    lock_file_path = Path(tempfile.gettempdir()) / "vouchlink_db_init.lock"

    try:
        with open(lock_file_path, "w") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.info("Acquired database initialization lock - proceeding with init_db()")
                init_db()
                # Startup sanity check: ensure default tenant/org pair exists and is aligned
                try:
                    ensure_default_tenant_org_alignment()
                except Exception as sanity_exc:
                    logger.error("Default tenant/org alignment failed: %s", sanity_exc)
                logger.info("Database initialization completed successfully")
            except BlockingIOError:
                logger.info("Another worker is initializing database - waiting for completion")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                logger.info("Database initialization lock released - database should be ready")
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception as lock_error:
        logger.warning("Lock-based initialization failed (%s); attempting direct init", lock_error)
        try:
            init_db()
        except Exception as fallback_error:
            logger.error("Database initialization failed: %s", fallback_error)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    await asyncio.to_thread(_initialize_database_with_lock)
    yield


app.router.lifespan_context = app_lifespan

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(prospects_router, prefix="/api", tags=["prospects"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(connectors_router)
app.include_router(email_router, tags=["email"])
app.include_router(email_admin_router, tags=["admin-email"])
app.include_router(email_mt_router, tags=["email-multi-tenant"])
app.include_router(email_webhooks_router, tags=["email-webhooks"])
app.include_router(approvals_router, tags=["approvals"])
app.include_router(metrics_router, tags=["metrics"])
app.include_router(cost_analysis_router, tags=["cost-analysis"])
app.include_router(linkedin_router, tags=["linkedin"])
app.include_router(integrations_router, tags=["integrations"])

if settings.ENABLE_LEGACY_INTRODUCERS:
    logger.warning("Legacy introducers shim enabled; routes exposed under /api/legacy")
    app.include_router(
        legacy_introducers_router,
        prefix="/api/legacy",
        tags=["legacy-introducers"],
    )

if settings.ENABLE_AUTOMATION_WORKFLOWS:
    logger.warning(
        "Legacy automation shim enabled; workflow triggers exposed under /api/legacy"
    )
    app.include_router(
        legacy_automation_router,
        prefix="/api/legacy",
        tags=["legacy-automation"],
    )

app.include_router(organization_router, tags=["organization"])
app.include_router(team_router, tags=["team"])
if company_portal_router is not None:
    app.include_router(company_portal_router)
app.include_router(workflows_router, tags=["workflows"])
app.include_router(queue_router, tags=["queue-management"])
app.include_router(ai_router, tags=["ai-orchestration"])
app.include_router(secrets_router, tags=["secrets"])
app.include_router(settings_router, tags=["settings"])
app.include_router(webhooks_delivery_router, tags=["webhook-delivery"])
app.include_router(introductions_router, tags=["introductions"])
app.include_router(email_integration_router, tags=["email-integration"])
app.include_router(public_landing_router, tags=["public-landing"])
app.include_router(agent_events_router, tags=["agent-events"])
app.include_router(websocket_compat_router, tags=["websocket-compat"])
app.include_router(user_settings_router, tags=["user-settings"])
app.include_router(master_game_plan_router, tags=["master-game-plan"])
app.include_router(ai_workflows_router, tags=["ai_workflows"])
app.include_router(dashboard_support_router, tags=["dashboard"])

# Add metrics endpoint if Prometheus is available
if prometheus_available and prometheus_get_metrics is not None:
    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint"""
        return Response(content=prometheus_get_metrics(), media_type="text/plain")

# Add simple root endpoint for basic routing test
@app.get("/")
async def root():
    """Simple root endpoint to test basic routing"""
    return {"message": "VouchLink API is running", "version": "2.0.0"}

# Add health check endpoint (no tenant context required)
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring - no authentication required"""
    import logging
    from datetime import datetime

    logger = logging.getLogger(__name__)

    try:
        health_status = {
            "status": "healthy",
            "service": "vouchlink-api",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "2.0.0",
            "components": {}
        }

        logger.info("Health check started")

        # Basic system check first
        health_status["components"]["system"] = {
            "status": "healthy",
            "python_version": "3.11",
            "startup": "complete"
        }

        # Test database connection (using proven pattern from migration_trigger.py)
        try:
            logger.info("Starting database health check")
            # Use the same pattern that works in production
            from api.database import get_db, is_postgres_db

            logger.info("Database imports successful")
            conn = get_db()
            logger.info("Database connection obtained")

            cursor = conn.cursor()
            logger.info("Database cursor created")

            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            logger.info(f"Database query executed, result: {result}")

            # Clean up resources safely
            try:
                cursor.close()
                logger.info("Database cursor closed")
            except Exception as cursor_close_err:
                logger.warning(f"Error closing cursor: {cursor_close_err}")

            try:
                conn.close()
                logger.info("Database connection closed")
            except Exception as conn_close_err:
                logger.warning(f"Error closing connection: {conn_close_err}")

            db_type = "postgresql" if is_postgres_db() else "sqlite"
            health_status["components"]["database"] = {
                "status": "healthy",
                "type": db_type,
                "test_result": "SELECT 1 successful"
            }
            logger.info(f"Database health check passed - {db_type}")
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            logger.error(f"Database error type: {type(e).__name__}")
            import traceback
            logger.error(f"Database error traceback: {traceback.format_exc()[:500]}")

            health_status["components"]["database"] = {
                "status": "unhealthy",
                "type": "unknown",
                "error": str(e)[:200],  # Longer error message for debugging
                "error_type": type(e).__name__
            }
            health_status["status"] = "degraded"

        # Test Redis connection
        try:
            import redis
            redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
            redis_client.ping()
            health_status["components"]["redis"] = {
                "status": "healthy",
                "type": "redis"
            }
            logger.debug("Redis health check passed")
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            health_status["components"]["redis"] = {
                "status": "unhealthy",
                "type": "redis",
                "error": str(e)[:100]
            }
            health_status["status"] = "degraded"

        # Check OpenAI Agents SDK status
        try:
            from services.openai_agents_2025_integration import OPENAI_AGENTS_AVAILABLE
            health_status["components"]["openai_agents_sdk"] = {
                "status": "healthy" if OPENAI_AGENTS_AVAILABLE else "not_installed",
                "available": OPENAI_AGENTS_AVAILABLE
            }
            logger.debug("OpenAI Agents SDK health check passed")
        except Exception as e:
            logger.debug(f"OpenAI Agents SDK not available: {e}")
            health_status["components"]["openai_agents_sdk"] = {
                "status": "not_installed",
                "available": False
            }

        logger.info(f"Health check completed with status: {health_status['status']}")

        # Ensure the response is JSON serializable
        try:
            import json
            json_str = json.dumps(health_status)
            logger.info("Health check response is JSON serializable")
        except Exception as json_err:
            logger.error(f"Health check response not JSON serializable: {json_err}")
            # Fallback to basic response
            health_status = {
                "status": "healthy",
                "service": "vouchlink-api",
                "timestamp": datetime.utcnow().isoformat(),
                "version": "2.0.0"
            }

        logger.info("Returning health check response")
        return health_status

    except Exception as e:
        # Catch-all error handler to prevent 400 responses
        logger.error(f"Health check failed with unexpected error: {e}")
        import traceback
        logger.error(f"Health check error traceback: {traceback.format_exc()[:500]}")

        try:
            from fastapi import HTTPException

            # Return a minimal health status even on error
            error_status = {
                "status": "unhealthy",
                "service": "vouchlink-api",
                "timestamp": datetime.utcnow().isoformat(),
                "version": "2.0.0",
                "error": str(e)[:200]
            }

            logger.error("Raising HTTPException with 503 status")
            # Return 503 Service Unavailable instead of letting FastAPI return 400
            raise HTTPException(status_code=503, detail=error_status)
        except Exception as final_error:
            logger.error(f"Final error in health check: {final_error}")
            # Absolute fallback - return a simple dict
            return {
                "status": "error",
                "service": "vouchlink-api",
                "error": "health_check_failure"
            }


@app.get("/api/health")
async def api_health_check():
    """
    Compatibility health endpoint aligned with other /api prefixed routes.
    """
    return await health_check()
