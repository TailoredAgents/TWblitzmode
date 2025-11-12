from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, AsyncIterator, Tuple, Set

import asyncio
import asyncpg
import os
import logging
from fastapi import Header, HTTPException, Depends, Request
from api.query_converter import convert_params, convert_query
from services.centralized_logging_service import LogCategory, LogLevel, log_structured

from core.settings import settings

from .auth import decode_token
from .tenant_repository import TenantRepository
from .tenant_context import set_tenant
from api.middleware.request_context import set_authenticated_context
from api.tenant_context import get_tenant

try:  # FastAPI layer running within src-aware path
    from src.services.database import db as sqlite_db
except ImportError:  # pragma: no cover - compatibility for legacy package layout
    from services.database import db as sqlite_db  # type: ignore


def _is_production_url(url: str) -> bool:
    lowered = url.lower()
    return any(domain in lowered for domain in ("render.com", "railway.app", "supabase.co"))


def _assert_database_url_safe(url: str) -> None:
    environment = settings.ENVIRONMENT.lower()
    # Allow production database URLs for E2E testing when USE_PROD_DB is set
    use_prod_db_for_testing = os.environ.get("USE_PROD_DB") == "1"
    if environment != "production" and _is_production_url(url) and not use_prod_db_for_testing:
        raise RuntimeError(
            "Refusing to use a production database URL outside the production environment."
        )


def _resolve_database_url(candidate: Optional[str]) -> str:
    url = candidate or settings.DATABASE_URL or os.environ.get("DATABASE_URL")
    if url:
        url = url.strip()
    if not url:
        url = "postgresql://localhost/vouchlink_dev"
    _assert_database_url_safe(url)
    return url


_DEFAULT_DATABASE_URL = _resolve_database_url(os.environ.get("DATABASE_URL"))

logger = logging.getLogger(__name__)

_KNOWN_OK_BILLING_STATUSES: Set[str] = {"active", "trial", "bypassed"}
_LOGGED_BILLING_STATUSES: Set[str] = set()


async def get_current_user(
    request: Request, authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or request.headers.get("cf-ray")
        or None
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        log_structured(
            LogLevel.WARNING,
            "auth.dep.missing_token",
            category=LogCategory.AUTHENTICATION,
            request_id=request_id,
        )
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except HTTPException:
        log_structured(
            LogLevel.WARNING,
            "auth.dep.invalid_token",
            category=LogCategory.AUTHENTICATION,
            request_id=request_id,
        )
        raise
    except Exception:
        log_structured(
            LogLevel.WARNING,
            "auth.dep.invalid_token",
            category=LogCategory.AUTHENTICATION,
            request_id=request_id,
        )
        raise HTTPException(status_code=401, detail="Invalid token")

    tenant_from_token = payload.get("tenant_id") or payload.get("organization_id")
    if tenant_from_token is None:
        log_structured(
            LogLevel.WARNING,
            "auth.dep.missing_tenant",
            category=LogCategory.AUTHENTICATION,
            request_id=request_id,
        )
        raise HTTPException(status_code=401, detail="Token missing tenant context")

    tenant_scope = str(tenant_from_token)

    # Get user data from database
    from api.database import get_db_connection

    header_tenant = getattr(request.state, "tenant_header", None)

    def _load_user_context(
        user_payload: Dict[str, Any],
        header_tenant_value: Optional[str],
        token_tenant_value: str,
    ) -> Tuple[Dict[str, Any], Optional[str], Optional[int]]:
        # Acquire a short-lived connection dedicated to this lookup
        with get_db_connection() as conn:
            user_id = user_payload.get("user_id")
            if not user_id:
                raise HTTPException(status_code=401, detail="Token missing user_id")

            with conn.cursor() as cur:
                cur.execute(
                    convert_query(
                        """
                        SELECT id, tenant_id, email, first_name, last_name, role
                        FROM users
                        WHERE id = ?
                          AND tenant_id = ?
                        """
                    ),
                    tuple(convert_params((user_id, token_tenant_value))),
                )
                user_row = cur.fetchone()

            if not user_row:
                log_structured(
                    LogLevel.WARNING,
                    "auth.dep.user_not_found",
                    category=LogCategory.AUTHENTICATION,
                    request_id=request_id,
                    extra_data={"tenant_id": token_tenant_value},
                )
                raise HTTPException(status_code=401, detail="User not found")

            tenant_raw = user_row["tenant_id"]
            tenant_id = str(tenant_raw) if tenant_raw is not None else None

            if header_tenant_value is not None and str(header_tenant_value) != str(tenant_id):
                logger.warning(
                    "Tenant context mismatch detected: header=%s token=%s",
                    header_tenant_value,
                    tenant_id,
                )
                log_structured(
                    LogLevel.WARNING,
                    "auth.dep.tenant_mismatch",
                    category=LogCategory.AUTHENTICATION,
                    request_id=request_id,
                    extra_data={
                        "header_tenant": str(header_tenant_value),
                        "token_tenant": str(tenant_id),
                    },
                )
                raise HTTPException(status_code=403, detail="Tenant context mismatch")

            org_row = None
            organization_id: Optional[int] = None
            subscription_tier: Optional[str] = None

            if tenant_id is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            convert_query("SELECT id, subscription_tier FROM organizations WHERE tenant_id = ?"),
                            tuple(convert_params((str(tenant_id),))),
                        )
                        org_row = cur.fetchone()
                except Exception as e:
                    # Gracefully handle missing organizations table or query errors
                    logger.warning(
                        "Failed to query organizations table for tenant %s: %s",
                        tenant_id,
                        e,
                    )
                    org_row = None

            if org_row:
                if org_row["id"] is not None:
                    organization_id = int(org_row["id"])
                subscription_tier = org_row["subscription_tier"]

            user_dict = {
                "id": user_row["id"],
                "user_id": user_row["id"],  # Add user_id alias for backward compatibility
                "tenant_id": tenant_id,
                "email": user_row["email"],
                "first_name": user_row["first_name"],
                "last_name": user_row["last_name"],
                "role": user_row["role"],
                "organization_id": organization_id,
                "subscription_tier": subscription_tier,
            }

            return user_dict, tenant_id, organization_id

    try:
        user_dict, tenant_id, organization_id = await asyncio.to_thread(
            _load_user_context,
            payload,
            header_tenant,
            tenant_scope,
        )
    except HTTPException:
        raise

    request.state.tenant_id = tenant_id
    request.state.user_id = user_dict["id"]
    if organization_id is not None:
        request.state.organization_id = organization_id

    account_record: Optional[Dict[str, Any]] = None
    if tenant_id:
        try:
            account_record = await sqlite_db.get_account_by_tenant(tenant_id)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Failed to hydrate account context for tenant_id=%s", tenant_id)
            account_record = None

    request.state.account = account_record
    request.state.plan = account_record.get("plan") if account_record else None
    set_authenticated_context(
        tenant_id=tenant_id,
        organization_id=organization_id,
        user_id=user_dict["id"],
    )
    if account_record:
        billing_status_value = account_record.get("billing_status") or "active"
        request.state.billing_status = billing_status_value
        normalized_status = str(billing_status_value or "").lower()
        if normalized_status not in _KNOWN_OK_BILLING_STATUSES and normalized_status not in _LOGGED_BILLING_STATUSES:
            _LOGGED_BILLING_STATUSES.add(normalized_status)
            scope_info = getattr(request, "scope", {}) if hasattr(request, "scope") else {}
            path_hint = "unknown"
            if isinstance(scope_info, dict):
                path_hint = scope_info.get("path") or "unknown"
            if path_hint == "unknown":
                try:
                    path_hint = request.url.path  # type: ignore[attr-defined]
                except Exception:
                    path_hint = "unknown"
            logger.warning(
                "Non-standard billing_status detected: %s (tenant=%s user=%s path=%s)",
                billing_status_value,
                tenant_id,
                request.state.user_id,
                path_hint,
            )
    else:
        request.state.billing_status = None

    try:
        request.state.tenant_context_token = set_tenant(tenant_id)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to set tenant context")
        request.state.tenant_context_token = None

    if account_record:
        user_dict["account_id"] = account_record.get("id")
        user_dict["account_plan"] = account_record.get("plan")
        user_dict["billing_status"] = account_record.get("billing_status") or "active"

    try:
        log_structured(
            LogLevel.INFO,
            "auth.dep.success",
            category=LogCategory.AUTHENTICATION,
            request_id=request_id,
            user_id=str(user_dict["id"]),
            tenant_id=tenant_id,
        )
    except Exception:
        pass

    return user_dict

async def get_current_admin(
    request: Request, authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """Ensure current user is an admin"""
    current_user = await get_current_user(request, authorization)

    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return current_user

@asynccontextmanager
async def get_connection(database_url: Optional[str] = None) -> AsyncIterator[asyncpg.Connection]:
    """Async context manager that yields a database connection and closes it safely."""

    url = _resolve_database_url(database_url)
    lowered = (url or "").lower()
    if not lowered.startswith(("postgresql://", "postgres://")):
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL DATABASE_URL is required for this endpoint. Please configure a valid DSN.",
        )

    try:
        conn = await asyncpg.connect(url)
    except Exception as exc:
        logger.error("Failed to connect to PostgreSQL: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL database is unavailable. Configure DATABASE_URL or start the database service.",
        ) from exc
    try:
        # Set RLS GUCs if a tenant context is active
        try:
            tenant = get_tenant()
            if tenant:
                await conn.execute("SELECT set_config('app.current_tenant_id', $1, true)", tenant)
                await conn.execute("SELECT set_config('app.current_organization_id', $1, true)", tenant)
        except Exception:
            logger.debug("Failed to set tenant GUCs on asyncpg connection", exc_info=True)

        yield conn
    finally:
        await conn.close()


async def get_connection_dependency() -> AsyncIterator[asyncpg.Connection]:
    """FastAPI dependency that provides a managed asyncpg connection."""

    async with get_connection() as conn:
        yield conn


async def get_tenant_repository(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> AsyncIterator[TenantRepository]:
    """
    Dependency that yields a tenant-scoped repository.
    """

    repo = TenantRepository(
        tenant_id=current_user["tenant_id"],
        organization_id=current_user.get("organization_id"),
    )
    try:
        yield repo
    finally:
        repo.close()
