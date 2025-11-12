from __future__ import annotations

"""
Lightweight database logging utilities.

These helpers provide a minimal interface used by the API database layer:
- scoped_query_context: no-op context manager for attaching labels/metadata
- start_query_log: returns a context dict used for follow-up logging
- log_query_success / log_query_failure: structured log emitters

Intentionally minimal to avoid heavy dependencies and to be safe during
application startup in environments without full observability wiring.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

_LOGGER = logging.getLogger("db")


@contextmanager
def scoped_query_context(*, label: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Iterator[None]:
    # Placeholder for future contextvars-based scoping. No-op for now.
    yield


def start_query_log(
    query: str,
    params: Any,
    *,
    tenant_id: Optional[str] = None,
    origin: Optional[str] = None,
    label: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = {
        "query": query,
        "params": params,
        "tenant_id": tenant_id,
        "origin": origin,
        "label": label,
        "metadata": metadata or {},
    }
    _LOGGER.debug("query_start", extra={k: v for k, v in ctx.items() if v is not None})
    return ctx


def log_query_success(ctx: Dict[str, Any], *, rowcount: Optional[int] = None) -> None:
    payload = dict(ctx)
    if rowcount is not None:
        payload["rowcount"] = rowcount
    _LOGGER.debug("query_ok", extra=payload)


def log_query_failure(ctx: Dict[str, Any], exc: Exception) -> None:
    payload = dict(ctx)
    payload["error_class"] = type(exc).__name__
    payload["error"] = str(exc)
    _LOGGER.error("query_error", extra=payload)
