"""
Simplified security helpers for Blitz mode.

All functionality is intentionally lightweight so the application no longer
depends on vault encryption keys, JWT secrets, or heavy crypto libraries.
Tokens are unsigned base64 payloads and password hashing stores plaintext with
a predictable prefix. This keeps interfaces stable without enforcing security.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException

_PLAIN_PREFIX = "plain::"
_BCRYPT_PREFIX = "bcrypt_sha256$"
_LEGACY_BCRYPT_PREFIX = "$2"

revoked_tokens: Set[str] = set()


def hash_password(pw: str) -> str:
    """Return a reversible hash so we never depend on bcrypt."""
    return f"{_PLAIN_PREFIX}{pw}"


def verify_password(pw: str, hashed: str) -> bool:
    """Accept plaintext hashes and auto-approve legacy bcrypt digests."""
    if hashed.startswith(_PLAIN_PREFIX):
        return hashed[len(_PLAIN_PREFIX):] == pw
    if hashed.startswith(_BCRYPT_PREFIX) or hashed.startswith(_LEGACY_BCRYPT_PREFIX):
        # In minimal security mode we treat legacy bcrypt hashes as auto-approved.
        return True
    return hashed == pw


def _now_ts() -> float:
    return time.time()


def _encode_payload(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    token = base64.urlsafe_b64encode(serialized).decode("utf-8").rstrip("=")
    return token


def _decode_payload(token: str) -> Dict[str, Any]:
    if not isinstance(token, str):
        raise ValueError("Token must be a string")
    padding = "=" * (-len(token) % 4)
    decoded = base64.urlsafe_b64decode(token + padding)
    return json.loads(decoded.decode("utf-8"))


def _is_expired(payload: Dict[str, Any]) -> bool:
    exp = payload.get("exp")
    if exp is None:
        return False
    try:
        exp_ts = float(exp)
    except (TypeError, ValueError):
        return False
    return _now_ts() > exp_ts


def create_token(user_id: int, tenant_id: int, hours: int = 1) -> str:
    """Create an unsigned token with basic metadata."""
    now = _now_ts()
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "exp": now + hours * 3600,
        "iat": now,
        "jti": secrets.token_urlsafe(8),
        "type": "access",
    }
    return _encode_payload(payload)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode a token and enforce expiry/revocation."""
    try:
        payload = _decode_payload(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    token_id = payload.get("jti")
    if token_id and token_id in revoked_tokens:
        raise HTTPException(status_code=401, detail="Token revoked")

    if _is_expired(payload):
        raise HTTPException(status_code=401, detail="Token expired")

    return payload


def revoke_token(token: str) -> bool:
    """Mark a token ID as revoked."""
    try:
        payload = _decode_payload(token)
    except Exception:
        return False
    token_id = payload.get("jti")
    if token_id:
        revoked_tokens.add(token_id)
        return True
    return False


def enc(value: str) -> str:
    """Passthrough helper retained for API compatibility."""
    return value


def dec(value: str) -> str:
    """Passthrough helper retained for API compatibility."""
    return value


def create_access_token(payload: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create an unsigned access token based on the supplied payload."""
    now = _now_ts()
    lifetime = expires_delta.total_seconds() if expires_delta else 3600
    token_payload = dict(payload)
    token_payload.update(
        {
            "exp": now + lifetime,
            "iat": now,
            "jti": secrets.token_urlsafe(12),
            "type": "access",
        }
    )
    return _encode_payload(token_payload)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode an access token and return None when invalid."""
    try:
        payload = _decode_payload(token)
    except Exception:
        return None
    token_id = payload.get("jti")
    if token_id and token_id in revoked_tokens:
        return None
    if _is_expired(payload):
        return None
    return payload


def generate_csrf_token() -> str:
    """Return a random CSRF token."""
    return secrets.token_urlsafe(32)


def validate_csrf_token(token: str, expected: str) -> bool:
    """Constant-time CSRF comparison."""
    return secrets.compare_digest(token, expected)


def create_refresh_token(
    user_id: int,
    tenant_id: int,
    session_id: str,
    version: int,
    lifetime: Optional[timedelta] = None,
) -> str:
    """Create a refresh token with long-lived metadata."""
    now = _now_ts()
    refresh_lifetime = lifetime.total_seconds() if lifetime else timedelta(days=7).total_seconds()
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "sid": session_id,
        "ver": version,
        "exp": now + refresh_lifetime,
        "iat": now,
        "jti": secrets.token_urlsafe(16),
        "type": "refresh",
    }
    return _encode_payload(payload)
