"""Role normalization utilities for the Tallwave Link platform.

This module centralizes the mapping between historical role labels and the
binary role model (`admin` / `user`). Callers should always pass raw roles
through :func:`normalize_role` before persisting or enforcing permissions to
guarantee consistency across services, migrations, and JWT claims.
"""

from __future__ import annotations

from typing import Optional

# Legacy aliases that should be treated as admin privileges. The strings are
# stored in lower-case to simplify normalization.
_ADMIN_ALIASES = {
    "admin",
    "org_admin",
    "organization_admin",
    "super_admin",
    "platform_admin",
    "owner",
    "ops",
    "support",
    "team_admin",
    "manager_admin",
}

# Legacy aliases that represent non-admin (standard user) access. Anything not
# explicitly listed defaults to the user tier to avoid accidentally elevating
# privileges.
_USER_ALIASES = {
    "user",
    "member",
    "viewer",
    "operator",
    "contributor",
    "readonly",
    "read_only",
    "observer",
    "guest",
    "analyst",
    "approver",
}

VALID_ROLES = {"admin", "user"}
DEFAULT_ROLE = "user"
KNOWN_ROLE_ALIASES = frozenset(_ADMIN_ALIASES | _USER_ALIASES)


def normalize_role(raw_role: Optional[str]) -> str:
    """Map any legacy role label onto the binary role model.

    Args:
        raw_role: Role string collected from the database, request payload, or
            a legacy integration. ``None`` or blank strings default to
            ``"user"``.

    Returns:
        The normalized role string: either ``"admin"`` or ``"user"``.
    """

    if not raw_role:
        return DEFAULT_ROLE

    role = raw_role.strip().lower()
    if role in _ADMIN_ALIASES:
        return "admin"
    if role in _USER_ALIASES:
        return "user"

    # Unknown roles default to the least privileged tier.
    return DEFAULT_ROLE


def is_admin(role: Optional[str]) -> bool:
    """Convenience helper to check for the admin tier."""

    return normalize_role(role) == "admin"


def require_valid_role(role: str) -> str:
    """Ensure the provided role already conforms to the binary model."""

    normalized = normalize_role(role)
    if normalized not in VALID_ROLES:
        # Defensive guard: in practice normalize_role never returns other
        # values, but raising helps surface misconfiguration in tests.
        raise ValueError(f"Unsupported role value: {role!r}")
    return normalized
