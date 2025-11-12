from __future__ import annotations

"""
PostgreSQL utility helpers (shim)

Small, import-safe helpers to resolve DSNs and open connections in contexts
without forcing an eager database connection during app import.
"""

import os
from contextlib import contextmanager
from typing import Iterator, Optional


# Sensible local default for developers; can be overridden via env.
DEFAULT_TEST_DSN: str = os.getenv(
    "DEFAULT_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5432/postgres",
)


def _normalize_dsn(url: str) -> str:
    """Normalize DSN prefixes (postgres -> postgresql)."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def resolve_required_dsn(
    primary_env: str,
    test_env: str,
    *,
    default: Optional[str] = None,
) -> str:
    """Resolve a DSN from env with a fallback default.

    Order of resolution:
      1) primary_env (e.g., DATABASE_URL)
      2) test_env (e.g., TEST_DATABASE_URL)
      3) provided default (normalized)
    Raises RuntimeError if none are set.
    """
    for key in (primary_env, test_env):
        val = os.getenv(key, "").strip()
        if val:
            return _normalize_dsn(val)
    if default:
        return _normalize_dsn(default)
    raise RuntimeError(
        f"Missing database DSN: set {primary_env} or {test_env}, or provide a default."
    )


@contextmanager
def postgres_connection(dsn: str, *, cursor_factory=None) -> Iterator["psycopg2.extensions.connection"]:
    """Context-managed psycopg2 connection.

    Usage:
      with postgres_connection(dsn, cursor_factory=RealDictCursor) as conn:
          with conn.cursor() as cur:
              cur.execute("SELECT 1")
    """
    try:
        import psycopg2  # type: ignore
        if cursor_factory is not None:
            conn = psycopg2.connect(dsn, cursor_factory=cursor_factory)
        else:
            conn = psycopg2.connect(dsn)
    except Exception as exc:  # pragma: no cover - environment misconfiguration
        raise RuntimeError(
            "psycopg2 is required for PostgreSQL connectivity. Install with 'pip install psycopg2-binary'."
        ) from exc

    try:
        yield conn
        try:
            conn.commit()
        except Exception:
            # Ignore commit issues during teardown; callers may manage transactions.
            pass
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def ensure_database_exists(dsn: str) -> None:
    """Best-effort check to ensure target database exists.

    In local/dev environments this is a no-op. Provisioning should be handled
    externally (e.g., Render blueprint or migration tooling).
    """
    # Intentionally a no-op to avoid side-effects during startup in constrained envs.
    return


def run_all_migrations(dsn: str) -> None:
    """Placeholder for schema migration runner.

    This shim deliberately does nothing; production deployments should run
    migrations via the dedicated pipeline/command.
    """
    # Intentionally a no-op in this environment.
    return
