"""
Compatibility bridge for legacy multi-tenant database helpers.

This module now enforces PostgreSQL-only operation while preserving the
historic ``api.mt_db`` interface consumed throughout the codebase.  It relies on
``src.services.database`` for tenant-aware connections and delegates schema
management to the shared PostgreSQL migration utilities.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any, Optional

from config import Config
from scripts.utils.postgres import (
    DEFAULT_TEST_DSN,
    ensure_database_exists,
    resolve_required_dsn,
    run_all_migrations,
)
from src.services.database import Database, db as _db_proxy, get_database

from api.database import bootstrap_postgres_schema
from core.settings import settings
from src.services.database_mode import describe_db_mode, is_native_mode, reset_db_mode_cache
from api.query_converter import convert_params, convert_query

try:
    import psycopg2
    from psycopg2 import extras as psycopg_extras
    from psycopg2 import pool as psycopg_pool
except ImportError:  # pragma: no cover - psycopg required in runtime environments
    psycopg2 = None  # type: ignore[assignment]
    psycopg_extras = None  # type: ignore[assignment]
    psycopg_pool = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
logger.debug("api.mt_db initializing with DB_COMPAT_MODE=%s", describe_db_mode())

_native_pool: "psycopg_pool.AbstractConnectionPool | None"
_native_pool = None


def _resolve_database_url() -> str:
    """
    Resolve the authoritative PostgreSQL DSN for tenant operations.

    The resolution mirrors the shared Postgres utility helpers so the same
    connection string is used across tests, local development, and CI.
    """
    return resolve_required_dsn("DATABASE_URL", "TEST_DATABASE_URL", default=DEFAULT_TEST_DSN)


def _ensure_row_factory(connection: Any) -> Any:
    """
    Historical callers expect sqlite-style dict rows.  The
    ``PostgreSQLDatabaseAdapter`` already exposes ``RealDictCursor`` semantics, so
    we simply return the connection unchanged for compatibility.
    """
    return connection


def _ensure_psycopg_available() -> None:
    if psycopg2 is None or psycopg_pool is None or psycopg_extras is None:
        raise RuntimeError(
            "psycopg2 is required for DB_COMPAT_MODE=native. Install psycopg2-binary in the runtime environment."
        )


class CompatCursor:
    """Cursor wrapper that normalises legacy SQLite-style queries for psycopg2."""

    __slots__ = ("_cursor",)

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None):
        statement = convert_query(sql)
        if params is None:
            self._cursor.execute(statement)
        elif isinstance(params, Mapping):
            self._cursor.execute(statement, params)
        else:
            converted = tuple(convert_params(tuple(params)))  # type: ignore[arg-type]
            self._cursor.execute(statement, converted)
        return self

    def executemany(self, sql: str, param_list):
        statement = convert_query(sql)
        if isinstance(param_list, Mapping):
            raise TypeError("executemany expects an iterable of parameter sequences, not mapping")
        materialised = list(param_list)
        converted = []
        for params in materialised:
            if isinstance(params, Mapping):
                converted.append(params)
            else:
                converted.append(tuple(convert_params(tuple(params))))  # type: ignore[arg-type]
        self._cursor.executemany(statement, converted)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size)

    def close(self):
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def __getattr__(self, item):
        return getattr(self._cursor, item)


class NativeConnectionWrapper:
    """Connection wrapper that returns compatibility cursors and returns itself to the pool on close."""

    __slots__ = ("_pool", "_connection", "tenant_id", "_returned")

    def __init__(self, pool, connection, tenant_id: Optional[Any] = None):
        self._pool = pool
        self._connection = connection
        self.tenant_id = str(tenant_id) if tenant_id is not None else None
        self._returned = False

    def cursor(self):
        cursor = self._connection.cursor(cursor_factory=psycopg_extras.RealDictCursor)
        return CompatCursor(cursor)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        if self._returned:
            return
        try:
            self._connection.rollback()
        except Exception:
            pass
        try:
            self._pool.putconn(self._connection)
        finally:
            self._returned = True

    def __getattr__(self, item):
        return getattr(self._connection, item)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _get_native_pool():
    global _native_pool
    if _native_pool is None:
        _ensure_psycopg_available()
        dsn = _resolve_database_url()
        _native_pool = psycopg_pool.ThreadedConnectionPool(
            minconn=int(os.getenv("DB_POOL_MIN", "1")),
            maxconn=int(os.getenv("DB_POOL_MAX", "10")),
            dsn=dsn,
            cursor_factory=psycopg_extras.RealDictCursor,
        )
    return _native_pool


def _reset_native_pool():
    global _native_pool
    if _native_pool is not None:
        try:
            _native_pool.closeall()
        except Exception:
            logger.debug("Failed to close native connection pool cleanly", exc_info=True)
        _native_pool = None


def _get_native_connection(*, tenant_id: Optional[Any] = None) -> NativeConnectionWrapper:
    pool = _get_native_pool()
    connection = pool.getconn()
    connection.autocommit = False
    return NativeConnectionWrapper(pool, connection, tenant_id=tenant_id)


def get_db(*, tenant_id: Optional[str] = None):
    """
    Return a tenant-aware database connection compatible with the legacy API.

    ``tenant_id`` is accepted for interface compatibility but is ignored because
    the Postgres adapter enforces tenant scoping via contextual guardrails.
    """
    if is_native_mode():
        return _get_native_connection(tenant_id=tenant_id)

    database = get_database()
    connection = database._get_connection()  # type: ignore[attr-defined]
    return _ensure_row_factory(connection)


def run_migrations() -> None:
    """
    Ensure the PostgreSQL schema is present and up to date.

    This replaces the old sqlite ``executescript`` workflow with the shared
    Postgres migration helpers and the compatibility bootstrap routines from
    ``api.database``.
    """
    dsn = _resolve_database_url()

    # Ensure DSN availability for other components consuming Config.DATABASE_URL
    Config.DATABASE_URL = dsn  # type: ignore[attr-defined]

    # Reset the lazy database proxy to pick up any DSN changes.
    try:
        _db_proxy.reset()
    except Exception:  # pragma: no cover - defensive guard
        logger.debug("Skipping database proxy reset", exc_info=True)

    ensure_database_exists(dsn)
    run_all_migrations(dsn)

    conn = get_db()
    try:
        bootstrap_postgres_schema(conn)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("bootstrap_postgres_schema failed: %s", exc)
        raise
    finally:
        conn.close()
    if is_native_mode():
        _reset_native_pool()
    reset_db_mode_cache()


def _row_value(row: Any, key: str, index: int) -> Optional[Any]:
    """Safely extract a column value regardless of row representation."""
    if row is None:
        return None
    if isinstance(row, Mapping):
        value = row.get(key)
        if value is not None:
            return value
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
        try:
            return row[index]
        except (IndexError, TypeError):
            return None
    return None


def get_or_create_admin_tenant(conn) -> int:
    """Ensure the dedicated Admin tenant record exists."""
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tenants WHERE name = %s", ("Admin",))
    row = cursor.fetchone()
    tenant_id = _row_value(row, "id", 0)
    if tenant_id is not None:
        return int(tenant_id)

    cursor.execute(
        "INSERT INTO tenants (name, status) VALUES (%s, %s) RETURNING id",
        ("Admin", "active"),
    )
    result = cursor.fetchone()
    conn.commit()
    return int(_row_value(result, "id", 0))


def ensure_admin_user(admin_email: str, password_hash: str) -> None:
    """
    Create or promote the Tallwave admin user and ensure the default organization exists.

    Render deployments expect a pre-seeded roster entry so the login page always shows at least
    one account. This helper now guarantees the Tallwave tenant, organization, user, and team
    member rows exist (and stay aligned) regardless of migration order.
    """
    normalized_email = (admin_email or "").strip().lower()
    if not normalized_email:
        logger.warning("ADMIN_EMAIL not configured; skipping admin bootstrap")
        return

    conn = get_db()
    try:
        cursor = conn.cursor()

        default_slug = (getattr(settings, "DEFAULT_ORGANIZATION_SLUG", "tallwave") or "tallwave").strip().lower()
        if not default_slug:
            default_slug = "tallwave"

        org_name = os.getenv("CLIENT_NAME", "Tallwave").strip() or "Tallwave"
        domain = getattr(settings, "DEFAULT_ORGANIZATION_DOMAIN", None) or "tallwave.com"
        subscription_tier = os.getenv("DEFAULT_SUBSCRIPTION_TIER", "enterprise")
        max_team_members = None  # unlimited seats

        # Ensure tenant exists (name tracked for legacy callers)
        cursor.execute(
            "SELECT id FROM tenants WHERE LOWER(name) = LOWER(%s) LIMIT 1",
            (org_name,),
        )
        tenant_row = cursor.fetchone()
        tenant_id = _row_value(tenant_row, "id", 0) if tenant_row is not None else None

        if tenant_id is None:
            cursor.execute(
                "INSERT INTO tenants (name, status) VALUES (%s, 'active') RETURNING id",
                (org_name,),
            )
            tenant_id = _row_value(cursor.fetchone(), "id", 0)

        if tenant_id is None:
            raise RuntimeError("Failed to ensure tenant for admin bootstrap")

        tenant_id = int(tenant_id)

        # Ensure organization exists and is aligned with the tenant (id == tenant_id to satisfy roster filtering)
        cursor.execute(
            """
            SELECT id, slug
            FROM organizations
            WHERE tenant_id = %s OR LOWER(slug) = LOWER(%s)
            ORDER BY id ASC
            LIMIT 1
            """,
            (tenant_id, default_slug),
        )
        org_row = cursor.fetchone()
        org_id = _row_value(org_row, "id", 0) if org_row is not None else None

        if org_id is None:
            cursor.execute(
                """
                INSERT INTO organizations (
                    id,
                    tenant_id,
                    name,
                    slug,
                    domain,
                    subscription_tier,
                    status,
                    max_team_members
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'active', %s)
                RETURNING id
                """,
                (tenant_id, tenant_id, org_name, default_slug, domain, subscription_tier, max_team_members),
            )
            org_id = _row_value(cursor.fetchone(), "id", 0)

        if org_id is None:
            raise RuntimeError("Failed to ensure Tallwave organization record")

        org_id = int(org_id)

        # Keep organization metadata fresh (handles slug/domain tweaks between deployments)
        cursor.execute(
            """
            UPDATE organizations
            SET name = %s,
                slug = %s,
                domain = %s,
                subscription_tier = COALESCE(%s, subscription_tier),
                status = 'active',
                max_team_members = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (org_name, default_slug, domain, subscription_tier, max_team_members, org_id),
        )

        # Ensure admin user exists (assign to tenant_id which aligns with organization id)
        cursor.execute(
            """
            SELECT id, role, tenant_id, first_name, last_name
            FROM users
            WHERE LOWER(email) = LOWER(%s)
            LIMIT 1
            """,
            (normalized_email,),
        )
        user_row = cursor.fetchone()
        first_name = os.getenv("ADMIN_FIRST_NAME", "Tallwave").strip() or "Tallwave"
        last_name = os.getenv("ADMIN_LAST_NAME", "Admin").strip() or "Admin"

        if user_row is None:
            cursor.execute(
                """
                INSERT INTO users (
                    tenant_id,
                    email,
                    password_hash,
                    first_name,
                    last_name,
                    role,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, 'admin', 'active')
                RETURNING id
                """,
                (tenant_id, normalized_email, password_hash, first_name, last_name),
            )
            user_id = _row_value(cursor.fetchone(), "id", 0)
        else:
            user_id = _row_value(user_row, "id", 0)
            current_role = _row_value(user_row, "role", 1)
            current_tenant = _row_value(user_row, "tenant_id", 2)

            updates: list[str] = []
            params: list[Any] = []

            if current_tenant is None or int(current_tenant) != tenant_id:
                updates.append("tenant_id = %s")
                params.append(tenant_id)

            if current_role != "admin":
                updates.append("role = 'admin'")

            updates.append("status = 'active'")
            updates.append("updated_at = NOW()")

            if updates:
                set_clause = ", ".join(updates)
                cursor.execute(
                    f"UPDATE users SET {set_clause} WHERE id = %s",
                    (*params, user_id),
                )

            cursor.execute(
                """
                UPDATE users
                SET first_name = COALESCE(NULLIF(first_name, ''), %s),
                    last_name = COALESCE(NULLIF(last_name, ''), %s)
                WHERE id = %s
                """,
                (first_name, last_name, user_id),
            )

        if user_id is None:
            raise RuntimeError("Failed to ensure admin user record")

        user_id = int(user_id)

        # Ensure team_members entry is linked to the admin (roster + approvals expect it)
        cursor.execute(
            """
            INSERT INTO team_members (
                organization_id,
                user_id,
                email,
                first_name,
                last_name,
                role,
                status,
                password_hash
            )
            VALUES (%s, %s, %s, %s, %s, 'admin', 'active', %s)
            ON CONFLICT (organization_id, email)
            DO UPDATE SET
                user_id = EXCLUDED.user_id,
                role = 'admin',
                status = 'active',
                first_name = COALESCE(EXCLUDED.first_name, team_members.first_name),
                last_name = COALESCE(EXCLUDED.last_name, team_members.last_name),
                password_hash = EXCLUDED.password_hash,
                updated_at = NOW()
            """,
            (org_id, user_id, normalized_email, first_name, last_name, password_hash),
        )

        conn.commit()
        logger.info(
            "Admin bootstrap complete (email=%s, tenant_id=%s, organization_id=%s, user_id=%s)",
            normalized_email,
            tenant_id,
            org_id,
            user_id,
        )
    except Exception:
        conn.rollback()
        logger.exception("Failed to ensure admin user")
        raise
    finally:
        conn.close()


def ensure_test_users() -> None:
    """Provision baseline test credentials for local development."""
    from api.security import hash_password  # Local import avoids circular import at module load time

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tenants WHERE name = %s", ("gmail.com",))
        row = cursor.fetchone()
        tenant_id = _row_value(row, "id", 0)

        if tenant_id is None:
            cursor.execute(
                "INSERT INTO tenants (name, status) VALUES (%s, %s) RETURNING id",
                ("gmail.com", "active"),
            )
            tenant_id = _row_value(cursor.fetchone(), "id", 0)
            conn.commit()

        tenant_id_int = int(tenant_id)
        password_hash = hash_password("VouchLinkAIadmin2")

        cursor.execute(
            "SELECT id FROM users WHERE email = %s AND tenant_id = %s",
            ("jeffreyjhacker@gmail.com", tenant_id_int),
        )
        existing = _row_value(cursor.fetchone(), "id", 0)

        if existing is not None:
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (password_hash, existing),
            )
            message = "Updated password for test user: jeffreyjhacker@gmail.com"
        else:
            cursor.execute(
                """
                INSERT INTO users (tenant_id, email, password_hash, first_name, last_name, role)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id_int,
                    "jeffreyjhacker@gmail.com",
                    password_hash,
                    "Jeffrey",
                    "Hacker",
                    "user",
                ),
            )
            message = "Created test user: jeffreyjhacker@gmail.com"

        conn.commit()
        logger.info(message)
    finally:
        conn.close()


__all__ = [
    "get_db",
    "run_migrations",
    "get_or_create_admin_tenant",
    "ensure_admin_user",
    "ensure_test_users",
    "Database",
    "get_database",
]
