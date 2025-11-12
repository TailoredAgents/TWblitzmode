"""No-op startup checks for Blitz mode."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def validate_core_secrets() -> None:
    """
    Blitz mode runs without secret validation so deployments do not require
    any application-level secrets. We keep the entry point so existing startup
    code can continue to call it safely.
    """
    logger.info("Minimal security mode active – core secret validation skipped.")
