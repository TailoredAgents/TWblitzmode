from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_active_tenant: ContextVar[Optional[str]] = ContextVar("active_tenant", default=None)


def set_tenant(tenant_id: Optional[str]) -> Token:
    """Persist the current tenant scope in a ContextVar and return its token."""
    if tenant_id is None:
        return _active_tenant.set(None)

    normalized = str(tenant_id).strip()
    if not normalized:
        return _active_tenant.set(None)
    return _active_tenant.set(normalized)


def get_tenant() -> Optional[str]:
    """Retrieve the tenant scope for the active context, if any."""
    value = _active_tenant.get()
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def reset_tenant(token: Token) -> None:
    """Reset the tenant scope to the value prior to the provided token."""
    _active_tenant.reset(token)
