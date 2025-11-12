"""Shim module to expose linkedin_people_search from src/services for legacy imports."""
from __future__ import annotations

try:
    from src.services.linkedin_people_search import *  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "src.services.linkedin_people_search is required for LinkedIn people search functionality"
    ) from exc
