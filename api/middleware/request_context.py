from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from services.centralized_logging_service import LogCategory, LogLevel, log_structured
from services.database_logging import scoped_query_context as scoped_db_query_context
from services.request_context import (
    bind_request_context,
    get_request_context,
    reset_request_context,
    update_request_context,
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach per-request context (request_id, tenant_id, correlation id) to logs."""

    def __init__(self, app, tenant_header: str = "x-tenant-id") -> None:
        super().__init__(app)
        self._tenant_header = tenant_header.lower()

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        correlation_id = request.headers.get("x-correlation-id") or request_id
        tenant_hint = request.headers.get(self._tenant_header)
        client_ip = self._extract_client_ip(request)

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        request.state.tenant_header = tenant_hint

        context_token = bind_request_context(
            request_id=request_id,
            correlation_id=correlation_id,
            tenant_id=tenant_hint,
            client_ip=client_ip,
            method=request.method,
            path=str(request.url.path),
        )

        start_time = time.perf_counter()
        db_metadata = {"method": request.method, "path": str(request.url.path)}
        db_label = f"http:{request.method}:{request.url.path}"

        try:
            with scoped_db_query_context(label=db_label, metadata=db_metadata):
                log_structured(
                    LogLevel.INFO,
                    "HTTP request started",
                    category=LogCategory.API,
                    method=request.method,
                    path=str(request.url.path),
                    ip=client_ip,
                    user_agent=request.headers.get("user-agent", "unknown"),
                )

                try:
                    response = await call_next(request)
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    log_structured(
                        LogLevel.ERROR,
                        "HTTP request failed",
                        category=LogCategory.API,
                        exc_info=exc,
                        method=request.method,
                        path=str(request.url.path),
                        duration_ms=round(duration_ms, 3),
                        status_code=getattr(getattr(exc, "response", None), "status_code", None)
                        or getattr(exc, "status_code", 500),
                    )
                    raise

                duration_ms = (time.perf_counter() - start_time) * 1000
                log_structured(
                    LogLevel.INFO,
                    "HTTP request completed",
                    category=LogCategory.API,
                    method=request.method,
                    path=str(request.url.path),
                    status_code=response.status_code,
                    duration_ms=round(duration_ms, 3),
                    ip=client_ip,
                )

                response.headers["x-request-id"] = request_id
                response.headers["x-correlation-id"] = correlation_id
                return response
        finally:
            reset_request_context(context_token)

    @staticmethod
    def _extract_client_ip(request: Request) -> Optional[str]:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        client = request.client
        return client.host if client else None


def set_authenticated_context(
    *,
    tenant_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> None:
    """
    Helper used by dependencies to enrich the current context once the user is authenticated.
    """
    update_request_context(
        tenant_id=str(tenant_id) if tenant_id is not None else None,
        organization_id=str(organization_id) if organization_id is not None else None,
        user_id=str(user_id) if user_id is not None else None,
    )
