"""
Request-scoped context utilities for structured logging.

Provides a small wrapper around ``contextvars`` so HTTP middleware,
background workers, and service layers can attach metadata such as
request_id, tenant_id, user_id, and correlation identifiers. Logging
helpers read these values automatically to enrich every record.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Dict, Optional

# Context dictionary that lives for the lifetime of a request/task.
_REQUEST_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "tallwave_request_context", default=None
)


def _ensure_context() -> Dict[str, Any]:
    """Return the mutable context dict for the current task."""
    ctx = _REQUEST_CONTEXT.get()
    if ctx is None:
        ctx = {}
        _REQUEST_CONTEXT.set(ctx)
    return ctx


def bind_request_context(**initial_values: Any) -> Token:
    """
    Initialize request context for the current execution scope.

    Returns the context token so callers (typically middleware) can
    reset state once the request finishes.
    """
    context_snapshot = {
        key: value for key, value in initial_values.items() if value is not None
    }
    return _REQUEST_CONTEXT.set(context_snapshot)


def reset_request_context(token: Token) -> None:
    """Reset the context to the state captured by ``token``."""
    try:
        _REQUEST_CONTEXT.reset(token)
    except RuntimeError:
        # Context might already be reset for background tasks; ignore.
        pass


def update_request_context(**values: Any) -> Dict[str, Any]:
    """
    Update the current request context in-place.

    Returns the resulting context dictionary so callers can read or log it.
    """
    ctx = _ensure_context()
    for key, value in values.items():
        if value is None:
            continue
        ctx[key] = value
    return ctx


def clear_request_context() -> None:
    """Explicitly clear any stored context."""
    _REQUEST_CONTEXT.set({})


def get_request_context() -> Dict[str, Any]:
    """Return a copy of the current context for read-only usage."""
    ctx = _REQUEST_CONTEXT.get()
    return dict(ctx) if ctx else {}


def get_request_id() -> Optional[str]:
    return get_request_context().get("request_id")


def get_correlation_id() -> Optional[str]:
    return get_request_context().get("correlation_id")


def get_tenant_id() -> Optional[str]:
    tenant = get_request_context().get("tenant_id")
    return str(tenant) if tenant is not None else None


def get_user_id() -> Optional[str]:
    user = get_request_context().get("user_id")
    return str(user) if user is not None else None
