"""Shim module to expose src.services.database_logging for legacy imports."""
from __future__ import annotations

try:
    from src.services.database_logging import *  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "src.services.database_logging module is required"
    ) from exc
