"""Shim module to expose src.services.database for legacy imports."""
from __future__ import annotations

try:
    from src.services.database import *  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "src.services.database module is required" 
    ) from exc
