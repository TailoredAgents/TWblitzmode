from __future__ import annotations

"""Minimal database service shim for compatibility.

Provides the small surface area referenced by legacy modules during import.
Runtime code paths for actual DB access should use the native adapters in
api.database / api.mt_db.
"""

from typing import Any


class _DBProxy:
    def reset(self) -> None:  # pragma: no cover - no-op
        return


db = _DBProxy()


class Database:
    """Placeholder class for compatibility; not instantiated in native mode."""

    def _get_connection(self) -> Any:  # pragma: no cover - not used in native mode
        raise RuntimeError("Legacy Database adapter is not available in this environment.")


def get_database() -> Database:  # pragma: no cover - not used in native mode
    return Database()

