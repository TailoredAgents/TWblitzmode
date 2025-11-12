from __future__ import annotations

"""Minimal JWT secret manager shim for local/dev.

Provides stable defaults so modules importing JWT configuration don't fail
at application startup in environments without provisioned secrets.
"""

import hashlib
import os
from dataclasses import dataclass


_DEFAULT_SECRET = os.getenv("JWT_SECRET", "dev-secret")


def get_jwt_secret() -> str:
    """Return the JWT secret, falling back to a development default."""
    return _DEFAULT_SECRET


@dataclass
class JWTSecretDiagnostics:
    source: str
    digest: str
    is_generated: bool


def get_jwt_secret_diagnostics() -> JWTSecretDiagnostics:
    secret = get_jwt_secret()
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]
    source = "env" if os.getenv("JWT_SECRET") else "default"
    return JWTSecretDiagnostics(source=source, digest=digest, is_generated=(source != "env"))

