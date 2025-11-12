"""
Critical startup validations to ensure production secrets are correctly configured.
"""

from __future__ import annotations

import logging
import os
from typing import List

from cryptography.fernet import Fernet

from api.jwt_secret_manager import (
    get_jwt_secret,
    get_jwt_secret_diagnostics,
)

logger = logging.getLogger(__name__)

_ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()


def _validate_enc_key() -> List[str]:
    issues: List[str] = []
    enc_key = os.getenv("ENC_KEY")
    if not enc_key:
        issues.append("ENC_KEY environment variable is missing.")
        return issues

    try:
        Fernet(enc_key.encode())
    except Exception:
        issues.append("ENC_KEY is not a valid Fernet key.")
    return issues


def validate_core_secrets() -> None:
    """
    Validate JWT/SECRET_KEY consistency and encryption key health.
    Raises RuntimeError when misconfigured to block unhealthy deployments.
    """
    issues: List[str] = []

    try:
        secret = get_jwt_secret()
        diagnostics = get_jwt_secret_diagnostics()
        logger.info(
            "JWT secret active (source=%s digest=%s generated=%s)",
            diagnostics.source,
            diagnostics.digest,
            diagnostics.is_generated,
        )
        if diagnostics.is_generated and _ENVIRONMENT == "production":
            issues.append("Ephemeral JWT secret detected in production (tokens reset every restart).")
    except RuntimeError as exc:
        issues.append(f"JWT secret misconfigured: {exc}")

    issues.extend(_validate_enc_key())

    # Enforce LLM provider/model invariants for production
    primary_model = (os.getenv("PRIMARY_MODEL") or "gpt-4.1").strip().lower()
    if _ENVIRONMENT == "production":
        if primary_model != "gpt-4.1":
            issues.append(
                f"Unsupported PRIMARY_MODEL '{primary_model}'. Production requires 'gpt-4.1'."
            )

    if issues:
        raise RuntimeError(
            "Critical secret validation failed: " + "; ".join(issues)
        )

    logger.info("Core secret validation completed successfully.")
