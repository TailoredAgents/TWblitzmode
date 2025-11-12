from __future__ import annotations

"""Database mode feature flag (shim).

Provides minimal functions to support compatibility checks during the
database refactor. Defaults to 'native' mode unless overridden via env.
"""

import os
from typing import Literal

_MODE_CACHE: str | None = None


def get_db_mode() -> Literal["native", "legacy"]:
    global _MODE_CACHE
    if _MODE_CACHE is not None:
        return _MODE_CACHE  # type: ignore[return-value]
    mode = os.getenv("DB_COMPAT_MODE", os.getenv("DATABASE_MODE", "native")).strip().lower()
    _MODE_CACHE = "legacy" if mode in {"legacy", "compat", "shim"} else "native"
    return _MODE_CACHE  # type: ignore[return-value]


def describe_db_mode() -> str:
    mode = get_db_mode()
    return "Native PostgreSQL adapter" if mode == "native" else "Legacy compatibility adapter"


def is_legacy_mode() -> bool:
    return get_db_mode() == "legacy"


def is_native_mode() -> bool:
    return get_db_mode() == "native"


def reset_db_mode_cache() -> None:
    global _MODE_CACHE
    _MODE_CACHE = None

