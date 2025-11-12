"""
Compatibility layer for auth primitives.

This re-exports helpers from api.security so legacy imports like
`from api.auth import decode_token` continue to work.
"""

from __future__ import annotations

from .security import (
    hash_password,
    verify_password,
    create_token,
    decode_token,
    revoke_token,
    create_access_token,
    decode_access_token,
    generate_csrf_token,
    validate_csrf_token,
    create_refresh_token,
    enc,
    dec,
)

__all__ = [
    "hash_password",
    "verify_password",
    "create_token",
    "decode_token",
    "revoke_token",
    "create_access_token",
    "decode_access_token",
    "generate_csrf_token",
    "validate_csrf_token",
    "create_refresh_token",
    "enc",
    "dec",
]

